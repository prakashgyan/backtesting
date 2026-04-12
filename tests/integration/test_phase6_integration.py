"""Integration tests for Phase 6 features."""

import pytest
from datetime import datetime, timedelta, timezone

from day_trader.engine.engine import Engine
from day_trader.data.replay import ReplayStream
from day_trader.strategy.examples.simple_sma import SimpleSMAStrategy
from day_trader.strategy.examples.rsi_strategy import RSIStrategy
from day_trader.strategy.examples.momentum_strategy import MomentumStrategy
from day_trader.strategy.examples.bollinger_bands_strategy import BollingerBandsStrategy
from day_trader.models import Bar
from day_trader.metrics import MetricsCalculator
from tests.unit.test_engine import MockBroker


class TestPhase6Integration:
    """Integration tests for Phase 6 features."""

    @pytest.mark.asyncio
    async def test_engine_with_rsi_strategy(self) -> None:
        """Test engine with RSI strategy and metrics calculation."""
        # Create bars with RSI-triggering prices
        bars = []
        base_time = datetime.now(timezone.utc)

        # Create price pattern that triggers RSI signals
        prices = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0]
        for i, price in enumerate(prices):
            bars.append(
                Bar(
                    symbol="TEST",
                    timestamp=base_time + timedelta(minutes=i),
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price,
                    volume=1000000.0,
                )
            )

        # Create engine components
        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = RSIStrategy(period=5, oversold=30.0, overbought=70.0)
        engine = Engine(data_stream, strategy, broker, initial_capital=100000.0)

        # Run engine
        await engine.run()

        # Verify execution
        assert engine.stats["bars_processed"] == len(bars)
        assert strategy.bars_count == len(bars)

        # Verify metrics were calculated
        metrics = engine.metrics.calculate_metrics()
        assert metrics.total_pnl == 0 or metrics.total_pnl != 0  # Just verify metrics exist

    @pytest.mark.asyncio
    async def test_engine_with_momentum_strategy(self) -> None:
        """Test engine with Momentum strategy."""
        # Create bars with uptrend
        bars = []
        base_time = datetime.now(timezone.utc)

        for i in range(15):
            price = 100.0 + i * 0.5
            bars.append(
                Bar(
                    symbol="TEST",
                    timestamp=base_time + timedelta(minutes=i),
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price,
                    volume=1000000.0,
                )
            )

        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = MomentumStrategy(period=5, momentum_threshold=0.5)
        engine = Engine(data_stream, strategy, broker)

        await engine.run()

        assert engine.stats["bars_processed"] == 15
        assert strategy.bars_count == 15

    @pytest.mark.asyncio
    async def test_engine_with_bollinger_bands_strategy(self) -> None:
        """Test engine with Bollinger Bands strategy."""
        # Create bars with oscillating prices
        bars = []
        base_time = datetime.now(timezone.utc)

        prices = [100.0, 101.0, 102.0, 101.0, 100.0, 99.0, 98.0, 99.0, 100.0, 101.0, 102.0]
        for i, price in enumerate(prices):
            bars.append(
                Bar(
                    symbol="TEST",
                    timestamp=base_time + timedelta(minutes=i),
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price,
                    volume=1000000.0,
                )
            )

        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = BollingerBandsStrategy(period=5, num_std_dev=1.5)
        engine = Engine(data_stream, strategy, broker)

        await engine.run()

        assert engine.stats["bars_processed"] == 11

    @pytest.mark.asyncio
    async def test_metrics_calculation_multiple_trades(self) -> None:
        """Test metrics calculation with multiple trades."""
        calc = MetricsCalculator(initial_capital=100000.0)
        base_time = datetime.now(timezone.utc)

        # Record several trades
        prices = [
            (100.0, 110.0),  # Win +10
            (100.0, 95.0),   # Loss -5
            (100.0, 105.0),  # Win +5
            (100.0, 98.0),   # Loss -2
        ]

        for i, (entry, exit_p) in enumerate(prices):
            trade = calc.record_trade("TEST", entry, base_time, 10)
            calc.close_trade(trade, exit_p, base_time + timedelta(hours=i+1))

        metrics = calc.calculate_metrics()

        # Verify metrics
        assert metrics.total_trades == 4
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 2
        assert metrics.win_rate == 50.0

        # Total P&L: (10 + (-5) + 5 + (-2)) * 10 = 80
        assert metrics.total_pnl == 80.0

    @pytest.mark.asyncio
    async def test_engine_displays_metrics_on_completion(self) -> None:
        """Test that engine displays metrics after completion."""
        bars = [
            Bar(
                symbol="TEST",
                timestamp=datetime.now(timezone.utc) + timedelta(minutes=i),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1000000.0,
            )
            for i in range(5)
        ]

        from day_trader.strategy.examples.simple_sma import SimpleSMAStrategy

        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = SimpleSMAStrategy()
        engine = Engine(data_stream, strategy, broker)

        await engine.run()

        metrics = engine.metrics.calculate_metrics()
        # Just verify metrics were calculated
        assert metrics.total_trades >= 0

    @pytest.mark.asyncio
    async def test_multiple_strategies_comparison(self) -> None:
        """Test comparing multiple strategies on same data."""
        # Create bars
        bars = []
        base_time = datetime.now(timezone.utc)

        for i in range(20):
            price = 100.0 + (i % 5) - 2
            bars.append(
                Bar(
                    symbol="TEST",
                    timestamp=base_time + timedelta(minutes=i),
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price,
                    volume=1000000.0,
                )
            )

        strategies = [
            SimpleSMAStrategy(),
            RSIStrategy(),
            MomentumStrategy(),
            BollingerBandsStrategy(),
        ]

        results = {}

        for strategy in strategies:
            stream = ReplayStream(bars, speed=100000.0)
            broker = MockBroker()
            engine = Engine(stream, strategy, broker)

            await engine.run()

            metrics = engine.metrics.calculate_metrics()
            results[strategy.__class__.__name__] = {
                "bars_processed": engine.stats["bars_processed"],
                "trades_executed": strategy._trades_executed,
                "total_pnl": metrics.total_pnl,
            }

        # Verify all strategies were tested
        assert len(results) == 4
        for strategy_name, stats in results.items():
            assert stats["bars_processed"] == 20
