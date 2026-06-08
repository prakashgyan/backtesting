"""Unit tests for dashboard query fallbacks."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from day_trader.dashboard import queries
from day_trader.run_tracking import RunTracker


def _seed_basic_run(db_path: Path, run_id: str = "run-1") -> None:
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, started_at_utc, ended_at_utc, status, strategy_name,
                broker_name, data_stream_name, symbol, mode, timeframe,
                metadata_json, initial_capital, bars_processed, trades_executed,
                errors, elapsed_seconds, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "2026-04-12T10:00:00+00:00",
                "2026-04-12T10:30:00+00:00",
                "COMPLETED",
                "day_trader.strategy.examples.simple_sma",
                "SimulatedBroker",
                "ReplayStream",
                "AAPL",
                "replay",
                "1Min",
                "{}",
                100000.0,
                120,
                2,
                0,
                1800.0,
                None,
            ),
        )
    conn.close()


def _insert_event(
    db_path: Path,
    run_id: str,
    event_time_utc: str,
    event_type: str,
    side: str | None,
    qty: float | None,
    fill_price: float | None,
    status: str | None,
    reason: str | None = None,
    details_json: str = "{}",
) -> None:
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO run_events (
                run_id, event_time_utc, event_type, symbol, side, qty,
                limit_price, fill_price, status, reason, source, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                event_time_utc,
                event_type,
                "AAPL",
                side,
                qty,
                fill_price,
                fill_price,
                status,
                reason,
                "test",
                details_json,
            ),
        )
    conn.close()


def test_fetch_run_detail_metrics_uses_fallback_when_csv_missing(tmp_path) -> None:
    db_path = tmp_path / "run_history.db"
    csv_path = tmp_path / "run_metrics.csv"

    tracker = RunTracker(db_path)
    tracker.close()

    _seed_basic_run(db_path)
    _insert_event(
        db_path,
        run_id="run-1",
        event_time_utc="2026-04-12T10:01:00+00:00",
        event_type="ORDER_REQUESTED",
        side="BUY",
        qty=10,
        fill_price=None,
        status="REQUESTED",
    )
    _insert_event(
        db_path,
        run_id="run-1",
        event_time_utc="2026-04-12T10:02:00+00:00",
        event_type="ORDER_RESULT",
        side="BUY",
        qty=10,
        fill_price=100.0,
        status="FILLED",
    )
    _insert_event(
        db_path,
        run_id="run-1",
        event_time_utc="2026-04-12T10:10:00+00:00",
        event_type="ORDER_RESULT",
        side="SELL",
        qty=10,
        fill_price=110.0,
        status="FILLED",
        details_json='{"position": {"symbol": "AAPL", "qty": 0, "market_value": 0, "unrealized_pnl": 0}}',
    )

    queries.configure_paths(db_path, csv_path)
    metrics = queries.fetch_run_detail_metrics("run-1")

    assert metrics is not None
    assert metrics["filled_orders"] == 2
    assert metrics["closed_trades"] == 1
    assert metrics["winning_trades"] == 1
    assert metrics["losing_trades"] == 0
    assert metrics["total_pnl"] == 100.0
    assert metrics["win_rate"] == 100.0
    assert metrics["returns_pct"] == 0.1


def test_fetch_run_detail_metrics_prefers_csv_values(tmp_path) -> None:
    db_path = tmp_path / "run_history.db"
    csv_path = tmp_path / "run_metrics.csv"

    tracker = RunTracker(db_path)
    tracker.close()

    _seed_basic_run(db_path)
    _insert_event(
        db_path,
        run_id="run-1",
        event_time_utc="2026-04-12T10:02:00+00:00",
        event_type="ORDER_RESULT",
        side="BUY",
        qty=10,
        fill_price=100.0,
        status="FILLED",
    )
    _insert_event(
        db_path,
        run_id="run-1",
        event_time_utc="2026-04-12T10:10:00+00:00",
        event_type="ORDER_RESULT",
        side="SELL",
        qty=10,
        fill_price=110.0,
        status="FILLED",
    )

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "run_timestamp_utc",
                "win_rate",
                "total_pnl",
                "returns_pct",
                "sharpe_ratio",
                "max_drawdown",
                "profit_factor",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "run_timestamp_utc": "2026-04-12T10:30:00+00:00",
                "win_rate": "65.5",
                "total_pnl": "222.5",
                "returns_pct": "1.25",
                "sharpe_ratio": "1.8",
                "max_drawdown": "4.2",
                "profit_factor": "2.4",
            }
        )

    queries.configure_paths(db_path, csv_path)
    metrics = queries.fetch_run_detail_metrics("run-1")

    assert metrics is not None
    assert metrics["total_pnl"] == 222.5
    assert metrics["returns_pct"] == 1.25
    assert metrics["win_rate"] == 65.5
    assert metrics["sharpe_ratio"] == 1.8
    assert metrics["max_drawdown"] == 4.2
    assert metrics["profit_factor"] == 2.4
