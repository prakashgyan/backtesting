"""Unit tests for Engine."""

import pytest
import asyncio

from day_trader.engine.engine import Engine
from day_trader.data.stream import DataStream
from day_trader.broker.base import BrokerBase
from day_trader.core.base import StrategyInterface
from day_trader.models import Bar, AccountInfo, Order, OrderSide, OrderStatus
from day_trader.core.exceptions import EngineError
from datetime import datetime, timezone
from typing import List, Optional


class MockDataStream(DataStream):
    """Mock data stream for testing."""

    def __init__(self, num_bars: int = 3):
        super().__init__()
        self.num_bars = num_bars

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def start(self) -> None:
        self._running = True
        for i in range(self.num_bars):
            bar = Bar(
                symbol="TEST",
                timestamp=datetime.now(timezone.utc),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1000000.0,
            )
            await self._emit_bar(bar)
        self._running = False

    async def stop(self) -> None:
        self._running = False


class MultiSymbolMockDataStream(DataStream):
    """Mock stream that emits an interleaved multi-symbol sequence."""

    def __init__(self, bars: List[Bar]):
        super().__init__()
        self._bars = bars

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def start(self) -> None:
        self._running = True
        for bar in self._bars:
            await self._emit_bar(bar)
        self._running = False

    async def stop(self) -> None:
        self._running = False


class MockBroker(BrokerBase):
    """Mock broker for testing."""

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_account(self) -> AccountInfo:
        return AccountInfo(
            cash=10000.0,
            buying_power=50000.0,
            portfolio_value=60000.0,
            equity=60000.0,
        )

    async def buy(self, symbol: str, qty: float, limit_price: Optional[float] = None) -> Order:
        return Order(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            filled_qty=qty,
            avg_fill_price=limit_price or 150.0,
        )

    async def sell(self, symbol: str, qty: float, limit_price: Optional[float] = None) -> Order:
        return Order(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            filled_qty=qty,
            avg_fill_price=limit_price or 150.0,
        )

    async def get_positions(self) -> List:
        return []

    async def get_position(self, symbol: str) -> Optional:
        return None


class MockStrategy(StrategyInterface):
    """Mock strategy for testing."""

    def __init__(self):
        self.bars_received = []
        self.initialized = False
        self.finalized = False
        self._orders: list = []

    @property
    def executed_orders(self):
        return self._orders

    async def initialize(self, broker) -> None:
        self.initialized = True

    async def on_bar(self, bar: Bar) -> None:
        self.bars_received.append(bar)

    async def finalize(self) -> None:
        self.finalized = True


class TestEngine:
    """Test cases for Engine."""

    @pytest.mark.asyncio
    async def test_engine_initialization(self) -> None:
        """Test engine initialization."""
        stream = MockDataStream()
        broker = MockBroker()
        strategy = MockStrategy()

        engine = Engine(stream, strategy, broker)
        assert not engine.running
        assert engine.stats["bars_processed"] == 0

    @pytest.mark.asyncio
    async def test_engine_run(self) -> None:
        """Test engine run flow."""
        stream = MockDataStream(num_bars=5)
        broker = MockBroker()
        strategy = MockStrategy()

        engine = Engine(stream, strategy, broker)

        # Run engine
        await engine.run()

        # Check results
        assert strategy.initialized
        assert strategy.finalized
        assert len(strategy.bars_received) == 5
        assert engine.stats["bars_processed"] == 5

    @pytest.mark.asyncio
    async def test_engine_stops_gracefully(self) -> None:
        """Test engine graceful shutdown."""
        stream = MockDataStream(num_bars=2)
        broker = MockBroker()
        strategy = MockStrategy()

        engine = Engine(stream, strategy, broker)
        await engine.run()

        assert not engine.running
        assert broker.connected is False
        assert stream.connected is False

    @pytest.mark.asyncio
    async def test_engine_stats(self) -> None:
        """Test engine statistics."""
        stream = MockDataStream(num_bars=3)
        broker = MockBroker()
        strategy = MockStrategy()

        engine = Engine(stream, strategy, broker)
        await engine.run()

        stats = engine.stats
        assert stats["bars_processed"] == 3
        assert stats["errors"] == 0
        assert stats["elapsed_seconds"] > 0

    @pytest.mark.asyncio
    async def test_engine_routes_interleaved_multi_symbol_bars(self) -> None:
        """Engine should deliver each bar unchanged, even with mixed symbols."""
        base_time = datetime.now(timezone.utc)
        bars = [
            Bar(
                symbol="SPY",
                timestamp=base_time,
                open=500.0,
                high=501.0,
                low=499.0,
                close=500.5,
                volume=1000000.0,
            ),
            Bar(
                symbol="QQQ",
                timestamp=base_time,
                open=430.0,
                high=431.0,
                low=429.0,
                close=430.5,
                volume=1000000.0,
            ),
            Bar(
                symbol="IWM",
                timestamp=base_time,
                open=210.0,
                high=211.0,
                low=209.0,
                close=210.5,
                volume=1000000.0,
            ),
            Bar(
                symbol="SPY",
                timestamp=base_time,
                open=501.0,
                high=502.0,
                low=500.0,
                close=501.5,
                volume=1000000.0,
            ),
        ]

        stream = MultiSymbolMockDataStream(bars)
        broker = MockBroker()
        strategy = MockStrategy()
        engine = Engine(stream, strategy, broker, run_metadata={"symbols": ["SPY", "QQQ", "IWM"]})

        await engine.run()

        assert engine.stats["bars_processed"] == 4
        assert [bar.symbol for bar in strategy.bars_received] == ["SPY", "QQQ", "IWM", "SPY"]
