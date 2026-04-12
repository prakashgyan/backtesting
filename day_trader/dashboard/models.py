"""Pydantic response models for the dashboard API endpoints."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class RunSummary(BaseModel):
    """One row in the /api/runs list, enriched with optional CSV metrics."""

    run_id: str
    started_at_utc: str
    ended_at_utc: Optional[str]
    status: str
    strategy_name: str
    broker_name: str
    data_stream_name: str
    symbol: Optional[str]
    mode: Optional[str]
    timeframe: Optional[str]
    initial_capital: float
    bars_processed: int
    trades_executed: int
    errors: int
    elapsed_seconds: float
    error_message: Optional[str]
    # Enriched from run_metrics.csv — None when no matching row
    win_rate: Optional[float] = None
    total_pnl: Optional[float] = None
    returns_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    profit_factor: Optional[float] = None


class RunDetail(RunSummary):
    """Single run detail — same as RunSummary plus raw metadata."""

    metadata_json: Optional[str] = None


class RunEvent(BaseModel):
    """One row from the run_events table."""

    event_id: int
    run_id: str
    event_time_utc: str
    event_type: str
    symbol: Optional[str]
    side: Optional[str]
    qty: Optional[float]
    limit_price: Optional[float]
    fill_price: Optional[float]
    status: Optional[str]
    reason: Optional[str]
    source: Optional[str]
    details_json: Optional[str]


class PnLPoint(BaseModel):
    """One point in the cumulative PnL time series."""

    event_time_utc: str
    cumulative_pnl: float
    trade_pnl: float
    side: str
    qty: float
    fill_price: float


class SummaryStats(BaseModel):
    """Aggregate stats for the dashboard header."""

    total_runs: int
    active_runs: int
    completed_runs: int
    failed_runs: int
    last_run_at: Optional[str]
    total_trades: int
    total_bars_processed: int


class PositionSnapshot(BaseModel):
    """One position snapshot extracted from event details, if available."""

    event_time_utc: str
    symbol: Optional[str]
    qty: Optional[float]
    market_value: Optional[float]
    unrealized_pnl: Optional[float]
    raw: dict[str, Any]


class RunDetailMetrics(BaseModel):
    """Detailed metrics for one run with computed fallback values."""

    run_id: str
    requested_orders: int
    filled_orders: int
    rejected_orders: int
    events_count: int
    filled_buy_qty: float
    filled_sell_qty: float
    closed_trades: int
    winning_trades: int
    losing_trades: int
    gross_profit: Optional[float]
    gross_loss: Optional[float]
    avg_win: Optional[float]
    avg_loss: Optional[float]
    total_pnl: Optional[float]
    realized_pnl: Optional[float]
    unrealized_pnl: Optional[float]
    returns_pct: Optional[float]
    win_rate: Optional[float]
    max_drawdown: Optional[float]
    sharpe_ratio: Optional[float]
    profit_factor: Optional[float]
    position_snapshots: list[PositionSnapshot]


class BenchmarkPoint(BaseModel):
    """One point in the benchmark comparison time series."""

    timestamp: str
    spy_pnl: Optional[float]
    spy_value: Optional[float]
    symbol_pnl: Optional[float]
    symbol_value: Optional[float]


class BenchmarkSeries(BaseModel):
    """Benchmark comparison data for a run."""

    run_id: str
    symbol: str
    initial_capital: float
    spy_start_price: Optional[float]
    spy_shares: Optional[float]
    symbol_start_price: Optional[float]
    symbol_shares: Optional[float]
    points: list[BenchmarkPoint]
    error: Optional[str] = None
