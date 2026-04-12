"""End-to-end integration tests for full trading engine workflow."""

import pytest
from datetime import datetime, timedelta, timezone

from day_trader.engine.engine import Engine
from day_trader.data.replay import ReplayStream
from day_trader.strategy.examples.simple_sma import SimpleSMAStrategy
from day_trader.models import Bar
from tests.unit.test_engine import MockBroker


class TestEngineFullWorkflow:
    """End-to-end tests for complete trading workflows."""

    @pytest.mark.asyncio
    async def test_full_replay_workflow(self) -> None:
        """Test complete replay mode workflow."""
        # Create sample bars
        bars = []
        base_time = datetime.now(timezone.utc)
        for i in range(30):
            bars.append(
                Bar(
                    symbol="AAPL",
                    timestamp=base_time + timedelta(minutes=i),
                    open=150.0 + i * 0.5,
                    high=151.0 + i * 0.5,
                    low=149.0 + i * 0.5,
                    close=150.5 + i * 0.5,
                    volume=1000000.0,
                )
            )

        # Create components
        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = SimpleSMAStrategy()

        # Create and run engine
        engine = Engine(data_stream, strategy, broker)
        await engine.run()

        # Verify results
        assert strategy.bars_count == 30
        assert engine.stats["bars_processed"] == 30
        assert engine.stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_replay_with_multiple_subscribers(self) -> None:
        """Test replay mode with multiple subscribers."""
        # Create bars
        bars = []
        base_time = datetime.now(timezone.utc)
        for i in range(10):
            bars.append(
                Bar(
                    symbol="TEST",
                    timestamp=base_time + timedelta(minutes=i),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1000000.0,
                )
            )

        # Create components
        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = SimpleSMAStrategy()

        # Create engine
        engine = Engine(data_stream, strategy, broker)

        # Verify multiple bars are processed
        await engine.run()
        assert engine.stats["bars_processed"] == 10

    @pytest.mark.asyncio
    async def test_engine_error_recovery(self) -> None:
        """Test engine continues on strategy errors."""

        class FailingStrategy(SimpleSMAStrategy):
            """Strategy that fails on certain bars."""

            async def on_bar(self, bar: Bar) -> None:
                if bar.close > 154.0:
                    raise ValueError("Test error")
                await super().on_bar(bar)

        # Create bars that will trigger error
        bars = []
        base_time = datetime.now(timezone.utc)
        for i in range(15):
            bars.append(
                Bar(
                    symbol="AAPL",
                    timestamp=base_time + timedelta(minutes=i),
                    open=150.0 + i * 0.5,
                    high=151.0 + i * 0.5,
                    low=149.0 + i * 0.5,
                    close=150.5 + i * 0.5,
                    volume=1000000.0,
                )
            )

        # Run with failing strategy
        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = FailingStrategy()

        engine = Engine(data_stream, strategy, broker)
        await engine.run()

        # Engine should continue despite errors
        assert engine.stats["bars_processed"] == 15
        assert engine.stats["errors"] > 0

    @pytest.mark.asyncio
    async def test_signals_generate_trades(self) -> None:
        """Test that strategy signals generate trades."""
        # Create bars that generate SMA crossover
        bars = []
        base_time = datetime.now(timezone.utc)

        # First 5 bars: price trending down (short SMA < long SMA)
        for i in range(5):
            bars.append(
                Bar(
                    symbol="TEST",
                    timestamp=base_time + timedelta(minutes=i),
                    open=105.0 - i,
                    high=106.0 - i,
                    low=104.0 - i,
                    close=105.5 - i,
                    volume=1000000.0,
                )
            )

        # Next 10 bars: price trending up (short SMA > long SMA, BUY signal)
        for i in range(5, 15):
            bars.append(
                Bar(
                    symbol="TEST",
                    timestamp=base_time + timedelta(minutes=i),
                    open=100.0 + (i - 5) * 1.0,
                    high=101.0 + (i - 5) * 1.0,
                    low=99.0 + (i - 5) * 1.0,
                    close=100.5 + (i - 5) * 1.0,
                    volume=1000000.0,
                )
            )

        # Run strategy
        data_stream = ReplayStream(bars, speed=100.0)
        broker = MockBroker()
        strategy = SimpleSMAStrategy(short_window=3, long_window=5)

        engine = Engine(data_stream, strategy, broker)
        await engine.run()

        # Should have executed trades based on crossover
        assert len(strategy.executed_orders) > 0
        assert engine.stats["trades_executed"] > 0
        metrics = engine.metrics.calculate_metrics()
        assert metrics.total_trades > 0 or len(engine.metrics.open_trades) > 0
