"""Unit tests for additional strategies."""

import pytest
from datetime import datetime, timedelta, timezone

from day_trader.strategy.examples.rsi_strategy import RSIStrategy
from day_trader.strategy.examples.momentum_strategy import MomentumStrategy
from day_trader.strategy.examples.bollinger_bands_strategy import BollingerBandsStrategy
from day_trader.models import Bar
from tests.unit.test_engine import MockBroker


class TestRSIStrategy:
    """Test cases for RSI strategy."""

    @pytest.mark.asyncio
    async def test_rsi_initialization(self) -> None:
        """Test RSI strategy initialization."""
        strategy = RSIStrategy(period=14, oversold=30.0, overbought=70.0)
        assert strategy.period == 14
        assert strategy.oversold == 30.0
        assert strategy.overbought == 70.0

    @pytest.mark.asyncio
    async def test_rsi_calculation(self) -> None:
        """Test RSI calculation."""
        strategy = RSIStrategy(period=5)

        # Add prices to simulate RSI calculation
        prices = [100.0, 101.0, 102.0, 101.5, 100.5, 99.0, 98.0, 97.5, 98.5, 99.5]

        for price in prices:
            strategy.prices.append(price)
            strategy.gains.append(0.0)
            strategy.losses.append(0.0)

        # Calculate RSI with enough data
        if len(strategy.gains) >= strategy.period:
            rsi = strategy._calculate_rsi()
            assert 0 <= rsi <= 100

    @pytest.mark.asyncio
    async def test_rsi_strategy_with_broker(self) -> None:
        """Test RSI strategy execution."""
        strategy = RSIStrategy(period=5, oversold=40.0, overbought=60.0)
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        base_time = datetime.now(timezone.utc)
        prices = [100.0, 99.0, 98.0, 97.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0]

        for i, price in enumerate(prices):
            bar = Bar(
                symbol="TEST",
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000000.0,
            )
            await strategy.on_bar(bar)

        await strategy.finalize()
        assert strategy.bars_count == 10

        await broker.disconnect()


class TestMomentumStrategy:
    """Test cases for Momentum strategy."""

    @pytest.mark.asyncio
    async def test_momentum_initialization(self) -> None:
        """Test momentum strategy initialization."""
        strategy = MomentumStrategy(period=10, momentum_threshold=1.0)
        assert strategy.period == 10
        assert strategy.momentum_threshold == 1.0

    @pytest.mark.asyncio
    async def test_momentum_calculation(self) -> None:
        """Test momentum calculation."""
        strategy = MomentumStrategy(period=5)

        # Add prices: from 100 to 105 (uptrend)
        for i in range(6):
            strategy.prices.append(100.0 + i)

        momentum = strategy._calculate_momentum()
        # (105 - 100) / 100 * 100 = 5%
        assert abs(momentum - 5.0) < 0.1

    @pytest.mark.asyncio
    async def test_momentum_strategy_execution(self) -> None:
        """Test momentum strategy with broker."""
        strategy = MomentumStrategy(period=5, momentum_threshold=1.0)
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        base_time = datetime.now(timezone.utc)
        # Prices trending up
        prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]

        for i, price in enumerate(prices):
            bar = Bar(
                symbol="TEST",
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000000.0,
            )
            await strategy.on_bar(bar)

        await strategy.finalize()
        assert strategy.bars_count == 8

        await broker.disconnect()


class TestBollingerBandsStrategy:
    """Test cases for Bollinger Bands strategy."""

    @pytest.mark.asyncio
    async def test_bollinger_bands_initialization(self) -> None:
        """Test Bollinger Bands strategy initialization."""
        strategy = BollingerBandsStrategy(period=20, num_std_dev=2.0)
        assert strategy.period == 20
        assert strategy.num_std_dev == 2.0

    @pytest.mark.asyncio
    async def test_bollinger_bands_calculation(self) -> None:
        """Test Bollinger Bands calculation."""
        strategy = BollingerBandsStrategy(period=5)

        # Add prices with some variation
        prices = [100.0, 101.0, 99.0, 102.0, 98.0]
        for price in prices:
            strategy.prices.append(price)

        middle, upper, lower = strategy._calculate_bands()

        # Middle should be the average
        assert abs(middle - 100.0) < 0.1
        # Upper should be greater than middle
        assert upper > middle
        # Lower should be less than middle
        assert lower < middle

    @pytest.mark.asyncio
    async def test_bollinger_bands_strategy_execution(self) -> None:
        """Test Bollinger Bands strategy with broker."""
        strategy = BollingerBandsStrategy(period=5)
        broker = MockBroker()

        await broker.connect()
        await strategy.initialize(broker)

        base_time = datetime.now(timezone.utc)
        prices = [100.0, 101.0, 99.0, 102.0, 98.0, 101.0, 99.0, 102.0]

        for i, price in enumerate(prices):
            bar = Bar(
                symbol="TEST",
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000000.0,
            )
            await strategy.on_bar(bar)

        await strategy.finalize()
        assert strategy.bars_count == 8

        await broker.disconnect()
