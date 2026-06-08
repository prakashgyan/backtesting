"""Unit tests for strategy implementations."""

import pytest
from datetime import datetime, timezone

from day_trader.strategy.base import Strategy
from day_trader.strategy.examples.simple_sma import SimpleSMAStrategy
from day_trader.strategy.examples.rsi_strategy import RSIStrategy
from day_trader.strategy.exp.mean_reversion import MeanReversionStrategy
from day_trader.models import Bar, OrderSide
from day_trader.core.exceptions import StrategyError
from tests.unit.test_engine import MockBroker


class DummyStrategy(Strategy):
    """Dummy strategy for testing."""

    async def on_bar(self, bar: Bar) -> None:
        pass


class TestStrategyBase:
    """Test cases for base Strategy class."""

    @pytest.mark.asyncio
    async def test_strategy_initialization(self) -> None:
        """Test strategy initialization."""
        strategy = DummyStrategy()
        assert strategy.broker is None
        assert strategy.signal is None

    @pytest.mark.asyncio
    async def test_strategy_initialize_with_broker(self) -> None:
        """Test initializing strategy with broker."""
        strategy = DummyStrategy()
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        assert strategy.broker is broker

        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_strategy_buy(self) -> None:
        """Test buy order execution."""
        strategy = DummyStrategy()
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        await strategy.buy("AAPL", qty=10, limit_price=150.0)
        assert strategy._trades_executed == 1

        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_strategy_sell(self) -> None:
        """Test sell order execution."""
        strategy = DummyStrategy()
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        await strategy.sell("AAPL", qty=10, limit_price=150.0)
        assert strategy._trades_executed == 1

        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_strategy_buy_without_broker(self) -> None:
        """Test that buy fails without broker initialization."""
        strategy = DummyStrategy()

        with pytest.raises(StrategyError):
            await strategy.buy("AAPL", qty=10)

    @pytest.mark.asyncio
    async def test_strategy_signal_property(self) -> None:
        """Test signal property."""
        strategy = DummyStrategy()

        strategy.signal = "BUY"
        assert strategy.signal == "BUY"

        strategy.signal = "SELL"
        assert strategy.signal == "SELL"

        strategy.signal = None
        assert strategy.signal is None

    def test_strategy_invalid_signal(self) -> None:
        """Test that invalid signal is rejected."""
        strategy = DummyStrategy()

        with pytest.raises(ValueError):
            strategy.signal = "INVALID"

    def test_strategy_default_multi_symbol_support_is_false(self) -> None:
        """Base strategy should be single-symbol by default."""
        strategy = DummyStrategy()
        assert strategy.supports_multi_symbol() is False


class TestSimpleSMAStrategy:
    """Test cases for SimpleSMAStrategy."""

    @pytest.mark.asyncio
    async def test_sma_strategy_initialization(self) -> None:
        """Test SMA strategy initialization."""
        strategy = SimpleSMAStrategy(short_window=5, long_window=20)
        assert strategy.short_window == 5
        assert strategy.long_window == 20

    @pytest.mark.asyncio
    async def test_sma_calculation(self) -> None:
        """Test SMA calculation."""
        strategy = SimpleSMAStrategy()

        # Add prices
        prices = [100.0, 101.0, 102.0, 101.0, 100.0]
        for price in prices:
            strategy.prices.append(price)

        # Calculate SMA
        sma = strategy._calculate_sma(len(prices))
        expected = sum(prices) / len(prices)
        assert abs(sma - expected) < 0.01

    @pytest.mark.asyncio
    async def test_sma_crossover_signal(self) -> None:
        """Test SMA crossover signal generation."""
        strategy = SimpleSMAStrategy(short_window=3, long_window=5)
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        # Create bars that trigger crossover
        base_time = datetime.now(timezone.utc)
        prices = [100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0]

        for i, price in enumerate(prices):
            bar = Bar(
                symbol="TEST",
                timestamp=base_time,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000000.0,
            )
            await strategy.on_bar(bar)

        # Should have executed trades
        assert strategy._trades_executed > 0

        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_sma_finalize(self) -> None:
        """Test strategy finalization."""
        strategy = SimpleSMAStrategy()
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        # Process a few bars
        for i in range(5):
            bar = Bar(
                symbol="TEST",
                timestamp=datetime.now(timezone.utc),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1000000.0,
            )
            await strategy.on_bar(bar)

        await strategy.finalize()
        assert strategy.bars_count == 5

        await broker.disconnect()


class TestStrategyMultiSymbolCapabilities:
    """Capability flags should reflect actual symbol-state safety."""

    def test_simple_sma_is_not_multi_symbol_safe(self) -> None:
        assert SimpleSMAStrategy().supports_multi_symbol() is False

    def test_rsi_is_multi_symbol_safe(self) -> None:
        assert RSIStrategy().supports_multi_symbol() is True

    def test_mean_reversion_is_multi_symbol_safe(self) -> None:
        assert MeanReversionStrategy().supports_multi_symbol() is True
