"""Trading metrics and performance analytics."""

import csv
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from day_trader.models import Order, OrderSide
from day_trader.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TradeMetrics:
    """Container for trading performance metrics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    returns_pct: float = 0.0

    def to_dict(self) -> dict:
        """Convert metrics to dictionary."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": round(self.total_pnl, 2),
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "win_rate": round(self.win_rate, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "profit_factor": round(self.profit_factor, 2),
            "returns_pct": round(self.returns_pct, 2),
        }


@dataclass
class Trade:
    """Represents a closed trade (entry and exit)."""

    symbol: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    qty: float = 0.0
    side: OrderSide = OrderSide.BUY
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def close(self, exit_price: float, exit_time: datetime) -> None:
        """Close the trade by setting exit price and time.

        Args:
            exit_price: Exit price
            exit_time: Exit time
        """
        self.exit_price = exit_price
        self.exit_time = exit_time

        if self.side == OrderSide.BUY:
            self.pnl = (exit_price - self.entry_price) * self.qty
        else:
            self.pnl = (self.entry_price - exit_price) * self.qty

        if self.entry_price != 0:
            self.pnl_pct = (self.pnl / (self.entry_price * self.qty)) * 100


class MetricsCalculator:
    """Calculates trading performance metrics."""

    def __init__(self, initial_capital: float = 100000.0):
        """Initialize metrics calculator.

        Args:
            initial_capital: Starting account capital
        """
        self.initial_capital = initial_capital
        self.closed_trades: List[Trade] = []
        self.open_trades: List[Trade] = []
        self.equity_curve: List[float] = [initial_capital]
        self.daily_returns: List[float] = []

    def record_trade(
        self,
        symbol: str,
        entry_price: float,
        entry_time: datetime,
        qty: float,
        side: OrderSide = OrderSide.BUY,
    ) -> Trade:
        """Record a new trade entry.

        Args:
            symbol: Stock symbol
            entry_price: Entry price
            entry_time: Entry time
            qty: Position size
            side: BUY or SELL

        Returns:
            Trade object
        """
        trade = Trade(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
            qty=qty,
            side=side,
        )
        self.open_trades.append(trade)
        return trade

    def close_trade(self, trade: Trade, exit_price: float, exit_time: datetime) -> None:
        """Close an open trade.

        Args:
            trade: Trade to close
            exit_price: Exit price
            exit_time: Exit time
        """
        trade.close(exit_price, exit_time)
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)

        # Update equity curve
        current_equity = self.get_equity()
        if not self.equity_curve or current_equity != self.equity_curve[-1]:
            self.equity_curve.append(current_equity)

    def get_equity(self) -> float:
        """Calculate current total equity including unrealized P&L.

        Returns:
            Current equity value
        """
        realized_pnl = sum(t.pnl for t in self.closed_trades)
        unrealized_pnl = sum(t.pnl for t in self.open_trades if t.exit_time is None)
        return self.initial_capital + realized_pnl + unrealized_pnl

    def calculate_metrics(self) -> TradeMetrics:
        """Calculate all trading performance metrics.

        Returns:
            TradeMetrics object with all calculated metrics
        """
        metrics = TradeMetrics()

        if not self.closed_trades:
            return metrics

        # Basic metrics
        metrics.total_trades = len(self.closed_trades)

        # Separate winners and losers
        winners = [t for t in self.closed_trades if t.pnl > 0]
        losers = [t for t in self.closed_trades if t.pnl < 0]

        metrics.winning_trades = len(winners)
        metrics.losing_trades = len(losers)
        metrics.win_rate = (len(winners) / len(self.closed_trades) * 100) if self.closed_trades else 0

        # P&L metrics
        metrics.gross_profit = sum(t.pnl for t in winners)
        metrics.gross_loss = abs(sum(t.pnl for t in losers))
        metrics.realized_pnl = sum(t.pnl for t in self.closed_trades)
        metrics.unrealized_pnl = sum(t.pnl for t in self.open_trades)
        metrics.total_pnl = metrics.realized_pnl + metrics.unrealized_pnl

        # Average metrics
        metrics.avg_win = (metrics.gross_profit / len(winners)) if winners else 0
        metrics.avg_loss = (metrics.gross_loss / len(losers)) if losers else 0

        # Profit factor (gross profit / gross loss)
        metrics.profit_factor = (
            metrics.gross_profit / metrics.gross_loss if metrics.gross_loss > 0 else 0
        )

        # Returns percentage
        metrics.returns_pct = (metrics.total_pnl / self.initial_capital) * 100

        # Drawdown
        metrics.max_drawdown = self._calculate_max_drawdown()

        # Sharpe ratio
        metrics.sharpe_ratio = self._calculate_sharpe_ratio()

        return metrics

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from equity curve.

        Returns:
            Maximum drawdown percentage
        """
        if len(self.equity_curve) < 2:
            return 0.0

        max_equity = self.equity_curve[0]
        max_dd = 0.0

        for equity in self.equity_curve:
            if equity > max_equity:
                max_equity = equity

            dd = (max_equity - equity) / max_equity * 100
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio.

        Args:
            risk_free_rate: Annual risk-free rate (default 2%)

        Returns:
            Sharpe ratio
        """
        if len(self.equity_curve) < 2:
            return 0.0

        # Calculate daily returns
        returns = []
        for i in range(1, len(self.equity_curve)):
            ret = (self.equity_curve[i] - self.equity_curve[i - 1]) / self.equity_curve[i - 1]
            returns.append(ret)

        if not returns:
            return 0.0

        # Calculate mean and std dev
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return 0.0

        # Sharpe ratio (annualized)
        sharpe = (mean_return - (risk_free_rate / 252)) / std_dev * math.sqrt(252)
        return sharpe

    def hydrate_from_orders(self, orders: List[Order]) -> int:
        """Rebuild closed/open trade lists from a list of filled orders using FIFO matching.

        Replaces the engine's inline lot-matching logic so MetricsCalculator
        owns the full lifecycle of trade records.

        Args:
            orders: All orders executed during the run, in chronological order.

        Returns:
            Number of orders processed (equals len(orders)).
        """
        self.closed_trades.clear()
        self.open_trades.clear()
        self.equity_curve = [self.initial_capital]

        open_lots: dict[str, deque] = defaultdict(deque)

        for order in orders:
            fill_price = order.avg_fill_price
            fill_qty = order.filled_qty or order.qty
            if fill_price <= 0 or fill_qty <= 0:
                continue

            fill_time = order.filled_at or order.created_at

            if order.side == OrderSide.BUY:
                lot = self.record_trade(
                    symbol=order.symbol,
                    entry_price=fill_price,
                    entry_time=fill_time,
                    qty=fill_qty,
                    side=OrderSide.BUY,
                )
                open_lots[order.symbol].append(lot)
                continue

            # SELL — close existing long lots in FIFO order
            remaining_qty = fill_qty
            while remaining_qty > 0 and open_lots[order.symbol]:
                lot = open_lots[order.symbol][0]
                if lot.qty <= remaining_qty:
                    self.close_trade(lot, fill_price, fill_time)
                    remaining_qty -= lot.qty
                    open_lots[order.symbol].popleft()
                else:
                    partial_lot = self.record_trade(
                        symbol=lot.symbol,
                        entry_price=lot.entry_price,
                        entry_time=lot.entry_time,
                        qty=remaining_qty,
                        side=lot.side,
                    )
                    self.close_trade(partial_lot, fill_price, fill_time)
                    lot.qty -= remaining_qty
                    remaining_qty = 0

        return len(orders)

    def append_run_metrics_to_csv(
        self,
        csv_path: Path,
        engine_stats: dict[str, Any],
        run_metadata: Optional[dict[str, Any]] = None,
        metrics: Optional[TradeMetrics] = None,
    ) -> Path:
        """Append a single run summary row to a CSV file.

        Args:
            csv_path: CSV file destination
            engine_stats: Engine run stats (bars/trades/errors/duration)
            run_metadata: Optional metadata (symbol/mode/strategy/etc.)
            metrics: Optional precomputed metrics to avoid recalculation

        Returns:
            Resolved path to the CSV file
        """
        run_metadata = run_metadata or {}
        metrics = metrics or self.calculate_metrics()

        row: dict[str, Any] = {
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "initial_capital": round(self.initial_capital, 2),
            "bars_processed": engine_stats.get("bars_processed", 0),
            "trades_executed": engine_stats.get("trades_executed", 0),
            "errors": engine_stats.get("errors", 0),
            "elapsed_seconds": round(float(engine_stats.get("elapsed_seconds", 0.0)), 4),
        }
        row.update(run_metadata)
        row.update(metrics.to_dict())

        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "run_timestamp_utc",
            "symbol",
            "mode",
            "strategy",
            "broker",
            "data_stream",
            "initial_capital",
            "bars_processed",
            "trades_executed",
            "errors",
            "elapsed_seconds",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "total_pnl",
            "gross_profit",
            "gross_loss",
            "realized_pnl",
            "unrealized_pnl",
            "win_rate",
            "avg_win",
            "avg_loss",
            "max_drawdown",
            "sharpe_ratio",
            "profit_factor",
            "returns_pct",
        ]

        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        logger.info("Run metrics appended to CSV: %s", csv_path)
        return csv_path
