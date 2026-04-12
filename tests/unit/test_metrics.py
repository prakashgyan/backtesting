"""Unit tests for metrics and analytics."""

import csv
import pytest
from datetime import datetime, timedelta, timezone

from day_trader.metrics import MetricsCalculator, Trade, TradeMetrics
from day_trader.models import OrderSide


class TestMetricsCalculator:
    """Test cases for MetricsCalculator."""

    def test_initialization(self) -> None:
        """Test metrics calculator initialization."""
        calc = MetricsCalculator(initial_capital=100000.0)
        assert calc.initial_capital == 100000.0
        assert len(calc.closed_trades) == 0
        assert len(calc.open_trades) == 0

    def test_record_and_close_trade(self) -> None:
        """Test recording and closing trades."""
        calc = MetricsCalculator(100000.0)

        # Record a trade
        entry_time = datetime.now(timezone.utc)
        trade = calc.record_trade("AAPL", 150.0, entry_time, 100, OrderSide.BUY)

        assert len(calc.open_trades) == 1

        # Close with profit
        exit_time = entry_time + timedelta(hours=1)
        calc.close_trade(trade, 155.0, exit_time)

        assert len(calc.closed_trades) == 1
        assert trade.pnl == 500.0  # (155 - 150) * 100

    def test_calculate_metrics_winning_trade(self) -> None:
        """Test metrics calculation for winning trades."""
        calc = MetricsCalculator(100000.0)

        # Winning trade
        entry_time = datetime.now(timezone.utc)
        trade = calc.record_trade("AAPL", 100.0, entry_time, 10, OrderSide.BUY)
        calc.close_trade(trade, 110.0, entry_time + timedelta(hours=1))

        metrics = calc.calculate_metrics()

        assert metrics.total_trades == 1
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 0
        assert metrics.win_rate == 100.0
        assert metrics.gross_profit == 100.0  # (110 - 100) * 10
        assert metrics.gross_loss == 0.0

    def test_calculate_metrics_losing_trade(self) -> None:
        """Test metrics calculation for losing trades."""
        calc = MetricsCalculator(100000.0)

        # Losing trade
        entry_time = datetime.now(timezone.utc)
        trade = calc.record_trade("AAPL", 100.0, entry_time, 10, OrderSide.BUY)
        calc.close_trade(trade, 95.0, entry_time + timedelta(hours=1))

        metrics = calc.calculate_metrics()

        assert metrics.total_trades == 1
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 1
        assert metrics.gross_loss == 50.0  # (100 - 95) * 10
        assert metrics.realized_pnl == -50.0

    def test_calculate_profit_factor(self) -> None:
        """Test profit factor calculation."""
        calc = MetricsCalculator(100000.0)
        base_time = datetime.now(timezone.utc)

        # 2 winning trades: +100, +200
        trade1 = calc.record_trade("AAPL", 100.0, base_time, 10, OrderSide.BUY)
        calc.close_trade(trade1, 110.0, base_time + timedelta(hours=1))

        trade2 = calc.record_trade("AAPL", 100.0, base_time + timedelta(hours=2), 10, OrderSide.BUY)
        calc.close_trade(trade2, 120.0, base_time + timedelta(hours=3))

        # 1 losing trade: -50
        trade3 = calc.record_trade("AAPL", 100.0, base_time + timedelta(hours=4), 10, OrderSide.BUY)
        calc.close_trade(trade3, 95.0, base_time + timedelta(hours=5))

        metrics = calc.calculate_metrics()

        assert metrics.gross_profit == 300.0  # 100 + 200
        assert metrics.gross_loss == 50.0
        assert abs(metrics.profit_factor - 6.0) < 0.01  # 300 / 50

    def test_max_drawdown(self) -> None:
        """Test maximum drawdown calculation."""
        calc = MetricsCalculator(100000.0)

        # Simulate equity curve: 100000 -> 105000 -> 95000 -> 100000
        calc.equity_curve = [100000.0, 105000.0, 95000.0, 100000.0]

        # Max drawdown from 105000 to 95000 = 9.52%
        max_dd = calc._calculate_max_drawdown()
        assert abs(max_dd - 9.52) < 0.1

    def test_metrics_to_dict(self) -> None:
        """Test metrics conversion to dictionary."""
        metrics = TradeMetrics(
            total_trades=10,
            winning_trades=7,
            losing_trades=3,
            total_pnl=1500.0,
            win_rate=70.0,
        )

        metrics_dict = metrics.to_dict()
        assert metrics_dict["total_trades"] == 10
        assert metrics_dict["win_rate"] == 70.0
        assert metrics_dict["total_pnl"] == 1500.0

    def test_append_run_metrics_to_csv_creates_file(self, tmp_path) -> None:
        """Test run metrics CSV file creation with headers and first row."""
        calc = MetricsCalculator(100000.0)
        base_time = datetime.now(timezone.utc)

        trade = calc.record_trade("AAPL", 100.0, base_time, 10, OrderSide.BUY)
        calc.close_trade(trade, 105.0, base_time + timedelta(hours=1))

        output = tmp_path / "run_metrics.csv"
        calc.append_run_metrics_to_csv(
            csv_path=output,
            engine_stats={
                "bars_processed": 50,
                "trades_executed": 2,
                "errors": 0,
                "elapsed_seconds": 12.3456,
            },
            run_metadata={
                "symbol": "AAPL",
                "mode": "replay",
                "strategy": "test.strategy",
                "broker": "SimulatedBroker",
                "data_stream": "ReplayStream",
            },
        )

        with output.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1
        row = rows[0]
        assert row["symbol"] == "AAPL"
        assert row["mode"] == "replay"
        assert row["strategy"] == "test.strategy"
        assert row["bars_processed"] == "50"
        assert row["trades_executed"] == "2"
        assert row["total_trades"] == "1"
        assert row["winning_trades"] == "1"

    def test_append_run_metrics_to_csv_appends_rows(self, tmp_path) -> None:
        """Test run metrics CSV appends without rewriting headers."""
        calc = MetricsCalculator(100000.0)
        output = tmp_path / "run_metrics.csv"

        calc.append_run_metrics_to_csv(
            csv_path=output,
            engine_stats={
                "bars_processed": 10,
                "trades_executed": 0,
                "errors": 0,
                "elapsed_seconds": 1.0,
            },
            run_metadata={
                "symbol": "AAPL",
                "mode": "replay",
                "strategy": "s1",
                "broker": "b1",
                "data_stream": "d1",
            },
        )

        calc.append_run_metrics_to_csv(
            csv_path=output,
            engine_stats={
                "bars_processed": 20,
                "trades_executed": 1,
                "errors": 1,
                "elapsed_seconds": 2.0,
            },
            run_metadata={
                "symbol": "TSLA",
                "mode": "live",
                "strategy": "s2",
                "broker": "b2",
                "data_stream": "d2",
            },
        )

        with output.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        assert rows[0]["symbol"] == "AAPL"
        assert rows[1]["symbol"] == "TSLA"


class TestTrade:
    """Test cases for Trade model."""

    def test_close_trade_buy(self) -> None:
        """Test closing a buy trade."""
        trade = Trade(
            symbol="AAPL",
            entry_time=datetime.now(timezone.utc),
            entry_price=150.0,
            qty=10,
            side=OrderSide.BUY,
        )

        exit_time = trade.entry_time
        trade.close(155.0, exit_time)

        assert trade.exit_price == 155.0
        assert trade.pnl == 50.0  # (155 - 150) * 10
        assert abs(trade.pnl_pct - 3.33) < 0.1

    def test_close_trade_sell(self) -> None:
        """Test closing a sell trade."""
        trade = Trade(
            symbol="AAPL",
            entry_time=datetime.now(timezone.utc),
            entry_price=150.0,
            qty=10,
            side=OrderSide.SELL,
        )

        exit_time = trade.entry_time
        trade.close(145.0, exit_time)

        assert trade.exit_price == 145.0
        assert trade.pnl == 50.0  # (150 - 145) * 10
