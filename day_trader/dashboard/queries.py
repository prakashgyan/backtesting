"""SQLite and CSV read logic for the dashboard.

All public functions are synchronous. Callers wrap them with
``asyncio.to_thread`` so they never block the FastAPI event loop.
"""

from __future__ import annotations

import csv as csv_module
import json
import math
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Module-level configuration (set once at server startup)
# ---------------------------------------------------------------------------

_CONFIG: dict[str, Optional[Path]] = {
    "db_path": None,
    "csv_path": None,
}


def configure_paths(db_path: Path, csv_path: Path) -> None:
    """Configure the paths used by all query functions."""
    _CONFIG["db_path"] = db_path
    _CONFIG["csv_path"] = csv_path


def _db_exists() -> bool:
    db_path = _CONFIG["db_path"]
    return db_path is not None and Path(db_path).exists()


def _get_conn() -> sqlite3.Connection:
    """Open a fresh read-only SQLite connection."""
    db_path = _CONFIG["db_path"]
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _get_conn_rw() -> sqlite3.Connection:
    """Open a fresh read-write SQLite connection."""
    db_path = _CONFIG["db_path"]
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# CSV metrics index (keyed by ended_at second-precision timestamp)
# ---------------------------------------------------------------------------

def _load_csv_index() -> dict[str, dict[str, Any]]:
    """Read run_metrics.csv and return a dict keyed by timestamp[:19]."""
    csv_path = _CONFIG["csv_path"]
    if csv_path is None or not csv_path.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    try:
        with csv_path.open(encoding="utf-8") as f:
            for row in csv_module.DictReader(f):
                ts = row.get("run_timestamp_utc", "")
                key = ts[:19]
                if key:
                    index[key] = row
    except OSError:
        pass
    return index


def _enrich_run(
    run: dict[str, Any],
    csv_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge optional CSV metrics into a run dict in-place."""
    ended = (run.get("ended_at_utc") or "")[:19]
    csv_row = csv_index.get(ended)
    for field in (
        "win_rate",
        "total_pnl",
        "returns_pct",
        "sharpe_ratio",
        "max_drawdown",
        "profit_factor",
    ):
        raw = csv_row.get(field) if csv_row else None
        try:
            run[field] = float(str(raw)) if raw not in (None, "", "nan") else None
        except (ValueError, TypeError):
            run[field] = None
    return run


# ---------------------------------------------------------------------------
# Public query functions
# ---------------------------------------------------------------------------

def fetch_summary() -> dict[str, Any]:
    """Return aggregate stats for the dashboard header."""
    if not _db_exists():
        return {
            "total_runs": 0,
            "active_runs": 0,
            "completed_runs": 0,
            "failed_runs": 0,
            "last_run_at": None,
            "total_trades": 0,
            "total_bars_processed": 0,
        }

    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_runs,
                SUM(CASE WHEN status = 'RUNNING' THEN 1 ELSE 0 END) AS active_runs,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_runs,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_runs,
                MAX(started_at_utc) AS last_run_at,
                SUM(trades_executed) AS total_trades,
                SUM(bars_processed) AS total_bars_processed
            FROM runs
            """
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {
            "total_runs": 0,
            "active_runs": 0,
            "completed_runs": 0,
            "failed_runs": 0,
            "last_run_at": None,
            "total_trades": 0,
            "total_bars_processed": 0,
        }

    return {
        "total_runs": row["total_runs"] or 0,
        "active_runs": row["active_runs"] or 0,
        "completed_runs": row["completed_runs"] or 0,
        "failed_runs": row["failed_runs"] or 0,
        "last_run_at": row["last_run_at"],
        "total_trades": row["total_trades"] or 0,
        "total_bars_processed": row["total_bars_processed"] or 0,
    }


def fetch_runs() -> list[dict[str, Any]]:
    """Return all runs ordered newest first, enriched with CSV metrics."""
    if not _db_exists():
        return []

    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY started_at_utc DESC"
        ).fetchall()
    finally:
        conn.close()

    csv_index = _load_csv_index()
    return [_enrich_run(dict(r), csv_index) for r in rows]


def fetch_run(run_id: str) -> Optional[dict[str, Any]]:
    """Return a single run by PK, or None if not found."""
    if not _db_exists():
        return None

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    csv_index = _load_csv_index()
    return _enrich_run(dict(row), csv_index)


def delete_run(run_id: str) -> bool:
    """Delete a run and its events. Returns True if deleted, False if not found."""
    if not _db_exists():
        return False

    conn = _get_conn_rw()
    try:
        # Check if run exists
        row = conn.execute(
            "SELECT run_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return False

        # Delete events first (foreign key), then run
        conn.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def fetch_events(run_id: str) -> list[dict[str, Any]]:
    """Return all events for a run, ordered by event_id ascending."""
    if not _db_exists():
        return []

    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY event_id ASC",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]


def compute_pnl_series(run_id: str) -> dict[str, Any]:
    """Compute cumulative PnL from FILLED ORDER_RESULT events using FIFO lot-matching.

    Returns a dict with:
      - ``points``: aggregate series (one point per filled trade across all symbols)
      - ``by_symbol``: per-symbol series (only populated when >1 symbol traded)
    """
    if not _db_exists():
        return {"points": [], "by_symbol": {}}

    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT event_time_utc, symbol, side, qty, fill_price
            FROM run_events
            WHERE run_id = ?
              AND event_type = 'ORDER_RESULT'
              AND status = 'FILLED'
            ORDER BY event_id ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    open_lots: dict[str, deque[tuple[float, float]]] = {}
    symbol_cumulative: dict[str, float] = {}
    cumulative_pnl = 0.0
    points: list[dict[str, Any]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        symbol: str = row["symbol"] or ""
        side: str = row["side"] or ""
        qty = float(row["qty"] or 0)
        fill_price = float(row["fill_price"] or 0)

        if symbol not in open_lots:
            open_lots[symbol] = deque()
        if symbol not in symbol_cumulative:
            symbol_cumulative[symbol] = 0.0
        if symbol not in by_symbol:
            by_symbol[symbol] = []

        trade_pnl = 0.0

        if side == "BUY":
            open_lots[symbol].append((qty, fill_price))
        elif side == "SELL":
            remaining = qty
            while remaining > 0 and open_lots[symbol]:
                lot_qty, lot_price = open_lots[symbol][0]
                close_qty = min(remaining, lot_qty)
                trade_pnl += (fill_price - lot_price) * close_qty
                remaining -= close_qty
                if close_qty >= lot_qty:
                    open_lots[symbol].popleft()
                else:
                    open_lots[symbol][0] = (lot_qty - close_qty, lot_price)
            cumulative_pnl += trade_pnl
            symbol_cumulative[symbol] += trade_pnl

        point: dict[str, Any] = {
            "event_time_utc": row["event_time_utc"],
            "cumulative_pnl": round(cumulative_pnl, 4),
            "trade_pnl": round(trade_pnl, 4),
            "side": side,
            "qty": qty,
            "fill_price": fill_price,
            "symbol": symbol,
            "symbol_cumulative_pnl": round(symbol_cumulative[symbol], 4),
        }
        points.append(point)
        by_symbol[symbol].append(point)

    # Only return per-symbol breakdown when more than one symbol was traded
    return {
        "points": points,
        "by_symbol": by_symbol if len(by_symbol) > 1 else {},
    }


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", "nan"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_position_snapshots(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for event in events:
        details_raw = event.get("details_json")
        if not details_raw:
            continue

        try:
            details = json.loads(details_raw)
        except (TypeError, ValueError):
            continue

        if not isinstance(details, dict):
            continue

        event_time = str(event.get("event_time_utc") or "")

        positions = details.get("positions")
        if isinstance(positions, list):
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                snapshots.append(
                    {
                        "event_time_utc": event_time,
                        "symbol": pos.get("symbol"),
                        "qty": _safe_float(pos.get("qty")),
                        "market_value": _safe_float(pos.get("market_value")),
                        "unrealized_pnl": _safe_float(pos.get("unrealized_pnl")),
                        "raw": pos,
                    }
                )

        position = details.get("position")
        if isinstance(position, dict):
            snapshots.append(
                {
                    "event_time_utc": event_time,
                    "symbol": position.get("symbol"),
                    "qty": _safe_float(position.get("qty")),
                    "market_value": _safe_float(position.get("market_value")),
                    "unrealized_pnl": _safe_float(position.get("unrealized_pnl")),
                    "raw": position,
                }
            )

    return snapshots


def _compute_fallback_metrics(
    run: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Optional[float] | int | float]:
    open_lots: dict[str, deque[tuple[float, float]]] = {}
    trade_pnls: list[float] = []
    cumulative_pnl = 0.0
    cumulative_points: list[float] = []
    filled_buy_qty = 0.0
    filled_sell_qty = 0.0

    for event in events:
        if event.get("event_type") != "ORDER_RESULT" or event.get("status") != "FILLED":
            continue

        symbol = str(event.get("symbol") or "")
        side = str(event.get("side") or "")
        qty = float(event.get("qty") or 0)
        fill_price = float(event.get("fill_price") or 0)

        if qty <= 0 or fill_price <= 0:
            continue

        if symbol not in open_lots:
            open_lots[symbol] = deque()

        if side == "BUY":
            filled_buy_qty += qty
            open_lots[symbol].append((qty, fill_price))
            continue

        if side != "SELL":
            continue

        filled_sell_qty += qty
        remaining = qty
        while remaining > 0 and open_lots[symbol]:
            lot_qty, lot_price = open_lots[symbol][0]
            close_qty = min(remaining, lot_qty)
            trade_pnl = (fill_price - lot_price) * close_qty
            trade_pnls.append(trade_pnl)
            cumulative_pnl += trade_pnl
            cumulative_points.append(cumulative_pnl)
            remaining -= close_qty

            if close_qty >= lot_qty:
                open_lots[symbol].popleft()
            else:
                open_lots[symbol][0] = (lot_qty - close_qty, lot_price)

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))
    closed_trades = len(trade_pnls)
    initial_capital = float(run.get("initial_capital") or 0)

    max_drawdown = 0.0
    if cumulative_points:
        peak = cumulative_points[0]
        for point in cumulative_points:
            if point > peak:
                peak = point
            if peak > 0:
                drawdown = ((peak - point) / peak) * 100
            else:
                drawdown = 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

    sharpe_ratio = 0.0
    if initial_capital > 0 and len(trade_pnls) > 1:
        returns = [p / initial_capital for p in trade_pnls]
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)
        if std_dev > 0:
            sharpe_ratio = (mean_return / std_dev) * math.sqrt(len(returns))

    total_pnl = cumulative_pnl if closed_trades > 0 else None
    returns_pct = (cumulative_pnl / initial_capital * 100) if initial_capital > 0 and closed_trades > 0 else None

    return {
        "filled_buy_qty": round(filled_buy_qty, 4),
        "filled_sell_qty": round(filled_sell_qty, 4),
        "closed_trades": closed_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "gross_profit": round(gross_profit, 4) if closed_trades > 0 else None,
        "gross_loss": round(gross_loss_abs, 4) if closed_trades > 0 else None,
        "avg_win": round(gross_profit / len(wins), 4) if wins else None,
        "avg_loss": round(gross_loss_abs / len(losses), 4) if losses else None,
        "total_pnl": round(total_pnl, 4) if total_pnl is not None else None,
        "realized_pnl": round(total_pnl, 4) if total_pnl is not None else None,
        "unrealized_pnl": None,
        "returns_pct": round(returns_pct, 4) if returns_pct is not None else None,
        "win_rate": round((len(wins) / closed_trades) * 100, 4) if closed_trades > 0 else None,
        "max_drawdown": round(max_drawdown, 4) if closed_trades > 0 else None,
        "sharpe_ratio": round(sharpe_ratio, 4) if closed_trades > 0 else None,
        "profit_factor": round(gross_profit / gross_loss_abs, 4)
        if gross_loss_abs > 0
        else None,
    }


def fetch_run_detail_metrics(run_id: str) -> Optional[dict[str, Any]]:
    """Return detailed run metrics with CSV fields overriding fallback values."""
    run = fetch_run(run_id)
    if run is None:
        return None

    events = fetch_events(run_id)
    fallback = _compute_fallback_metrics(run, events)

    def fallback_float(name: str) -> float:
        raw = fallback.get(name)
        if isinstance(raw, (int, float)):
            return float(raw)
        return 0.0

    def fallback_int(name: str) -> int:
        raw = fallback.get(name)
        if isinstance(raw, (int, float)):
            return int(raw)
        return 0

    def pick_metric(name: str) -> Optional[float]:
        value = run.get(name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
        raw = fallback.get(name)
        return float(raw) if isinstance(raw, (int, float)) else None

    requested_orders = sum(1 for e in events if e.get("event_type") == "ORDER_REQUESTED")
    filled_orders = sum(
        1
        for e in events
        if e.get("event_type") == "ORDER_RESULT" and e.get("status") == "FILLED"
    )
    rejected_orders = sum(
        1
        for e in events
        if e.get("event_type") in ("ORDER_RESULT", "ORDER_FAILED") and e.get("status") == "REJECTED"
    )

    return {
        "run_id": run_id,
        "requested_orders": requested_orders,
        "filled_orders": filled_orders,
        "rejected_orders": rejected_orders,
        "events_count": len(events),
        "filled_buy_qty": fallback_float("filled_buy_qty"),
        "filled_sell_qty": fallback_float("filled_sell_qty"),
        "closed_trades": fallback_int("closed_trades"),
        "winning_trades": fallback_int("winning_trades"),
        "losing_trades": fallback_int("losing_trades"),
        "gross_profit": pick_metric("gross_profit"),
        "gross_loss": pick_metric("gross_loss"),
        "avg_win": pick_metric("avg_win"),
        "avg_loss": pick_metric("avg_loss"),
        "total_pnl": pick_metric("total_pnl"),
        "realized_pnl": pick_metric("realized_pnl"),
        "unrealized_pnl": pick_metric("unrealized_pnl"),
        "returns_pct": pick_metric("returns_pct"),
        "win_rate": pick_metric("win_rate"),
        "max_drawdown": pick_metric("max_drawdown"),
        "sharpe_ratio": pick_metric("sharpe_ratio"),
        "profit_factor": pick_metric("profit_factor"),
    }


def fetch_benchmark_series(run_id: str) -> Optional[dict[str, Any]]:
    """Fetch benchmark comparison data for a run.

    Computes what the initial capital would be worth invested in SPY (buy-and-hold).
    For single-symbol runs, also computes the symbol's own buy-and-hold line.
    For multi-symbol runs, only SPY is shown (portfolio buy-and-hold is ambiguous).

    For replay mode, uses data_start_date/data_end_date (the actual historical
    data range) instead of started_at_utc/ended_at_utc (wall-clock backtest time).
    """
    run = fetch_run(run_id)
    if run is None:
        return None

    # Resolve symbol list from metadata_json (authoritative) falling back to symbol column
    metadata_json_raw = run.get("metadata_json")
    symbols: list[str] = []
    if metadata_json_raw:
        try:
            meta = json.loads(metadata_json_raw)
            raw_symbols = meta.get("symbols")
            if isinstance(raw_symbols, list):
                symbols = [str(s) for s in raw_symbols if s]
        except (json.JSONDecodeError, TypeError):
            pass
    if not symbols:
        raw_sym = run.get("symbol") or ""
        symbols = [s.strip() for s in raw_sym.split(",") if s.strip()]

    is_multi = len(symbols) > 1
    # Primary symbol for display and single-symbol buy-hold benchmark
    symbol = symbols[0] if symbols else ""

    initial_capital = float(run.get("initial_capital") or 100000)
    mode = run.get("mode") or "live"

    # For replay mode, prefer data_start_date/data_end_date (actual historical data range)
    # Fall back to started_at_utc/ended_at_utc for live mode or if data dates missing
    data_start_date_str = run.get("data_start_date")
    data_end_date_str = run.get("data_end_date")
    started_at = run.get("started_at_utc") or ""
    ended_at = run.get("ended_at_utc") or ""

    if not symbol:
        return {
            "run_id": run_id,
            "symbol": symbol,
            "initial_capital": initial_capital,
            "spy_start_price": None,
            "spy_shares": None,
            "symbol_start_price": None,
            "symbol_shares": None,
            "points": [],
            "error": "Missing symbol",
        }

    # Parse dates - use data dates for replay, run dates otherwise
    from datetime import datetime, date
    try:
        if mode == "replay" and data_start_date_str and data_end_date_str:
            # Replay mode: use the actual historical data date range
            start_date = date.fromisoformat(data_start_date_str)
            end_date = date.fromisoformat(data_end_date_str)
        elif started_at:
            # Live mode or fallback: use run timestamps
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            start_date = start_dt.date()
            if ended_at:
                end_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                end_date = end_dt.date()
            else:
                end_date = date.today()
        else:
            raise ValueError("No valid date range available")
    except (ValueError, TypeError) as e:
        return {
            "run_id": run_id,
            "symbol": symbol,
            "initial_capital": initial_capital,
            "spy_start_price": None,
            "spy_shares": None,
            "symbol_start_price": None,
            "symbol_shares": None,
            "points": [],
            "error": f"Invalid date format: {e}",
        }

    # Fetch daily bars for benchmarks (always use 1d timeframe for comparison)
    # Daily bars are more appropriate for performance comparison and much lighter
    try:
        from day_trader.config import get_settings
        from day_trader.data.cache import DataCache

        settings = get_settings()
        cache = DataCache(settings)

        spy_bars = cache.fetch_bars("SPY", start_date, end_date, "1d")
        # For multi-symbol runs, skip the per-symbol buy-hold line — it's ambiguous
        # which symbol to benchmark against a portfolio strategy.
        symbol_bars = (
            cache.fetch_bars(symbol, start_date, end_date, "1d")
            if not is_multi and symbol != "SPY"
            else None
        )
    except Exception as e:
        return {
            "run_id": run_id,
            "symbol": symbol,
            "initial_capital": initial_capital,
            "spy_start_price": None,
            "spy_shares": None,
            "symbol_start_price": None,
            "symbol_shares": None,
            "points": [],
            "error": f"Failed to fetch benchmark data: {str(e)}",
        }

    if not spy_bars:
        return {
            "run_id": run_id,
            "symbol": symbol,
            "initial_capital": initial_capital,
            "spy_start_price": None,
            "spy_shares": None,
            "symbol_start_price": None,
            "symbol_shares": None,
            "points": [],
            "error": "No SPY benchmark bar data available",
        }

    # SPY buy-hold
    spy_start_price = spy_bars[0].close
    spy_shares = initial_capital / spy_start_price if spy_start_price > 0 else 0

    # Single-symbol buy-hold (None for multi-symbol runs or when symbol == SPY)
    symbol_start_price: Optional[float] = None
    symbol_shares: float = 0.0
    symbol_by_date: dict[str, float] = {}
    if symbol_bars:
        symbol_start_price = symbol_bars[0].close
        symbol_shares = initial_capital / symbol_start_price if symbol_start_price > 0 else 0
        for bar in symbol_bars:
            symbol_by_date[bar.timestamp.date().isoformat()] = bar.close

    # Compute benchmark points for each SPY day
    points: list[dict[str, Any]] = []
    for spy_bar in spy_bars:
        date_key = spy_bar.timestamp.date().isoformat()
        spy_value = spy_shares * spy_bar.close
        spy_pnl = spy_value - initial_capital

        symbol_price = symbol_by_date.get(date_key)
        sym_pnl: Optional[float] = None
        sym_value: Optional[float] = None
        if symbol_price is not None:
            sym_value = symbol_shares * symbol_price
            sym_pnl = sym_value - initial_capital

        points.append({
            "timestamp": spy_bar.timestamp.isoformat(),
            "spy_pnl": round(spy_pnl, 2),
            "spy_value": round(spy_value, 2),
            "symbol_pnl": round(sym_pnl, 2) if sym_pnl is not None else None,
            "symbol_value": round(sym_value, 2) if sym_value is not None else None,
        })

    return {
        "run_id": run_id,
        "symbol": symbol,
        "initial_capital": initial_capital,
        "spy_start_price": round(spy_start_price, 2),
        "spy_shares": round(spy_shares, 4),
        "symbol_start_price": round(symbol_start_price, 2) if symbol_start_price is not None else None,
        "symbol_shares": round(symbol_shares, 4),
        "points": points,
        "total_days": len(spy_bars),
        "error": None,
    }
