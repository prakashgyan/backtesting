"""Unit tests for DataStream."""

import pytest
import asyncio

from day_trader.data.stream import DataStream
from day_trader.models import Bar
from datetime import datetime, timezone


class MockDataStream(DataStream):
    """Mock implementation for testing."""

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def start(self) -> None:
        self._running = True
        # Emit a few test bars
        for i in range(3):
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

    async def stop(self) -> None:
        self._running = False


class TestDataStream:
    """Test cases for DataStream base class."""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self) -> None:
        """Test connect and disconnect."""
        stream = MockDataStream()
        assert not stream.connected

        await stream.connect()
        assert stream.connected

        await stream.disconnect()
        assert not stream.connected

    @pytest.mark.asyncio
    async def test_subscribe_callback(self) -> None:
        """Test subscribing callback to stream."""
        stream = MockDataStream()
        bars_received = []

        async def on_bar(bar: Bar) -> None:
            bars_received.append(bar)

        await stream.subscribe(on_bar)
        assert len(stream._callbacks) == 1

        await stream.connect()
        await stream.start()

        assert len(bars_received) == 3

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self) -> None:
        """Test multiple callbacks receive all bars."""
        stream = MockDataStream()
        bars1 = []
        bars2 = []

        async def on_bar1(bar: Bar) -> None:
            bars1.append(bar)

        async def on_bar2(bar: Bar) -> None:
            bars2.append(bar)

        await stream.subscribe(on_bar1)
        await stream.subscribe(on_bar2)

        await stream.connect()
        await stream.start()

        assert len(bars1) == 3
        assert len(bars2) == 3

    @pytest.mark.asyncio
    async def test_callback_error_handling(self) -> None:
        """Test that callback errors don't crash stream."""
        stream = MockDataStream()
        bars_received = []

        async def failing_callback(bar: Bar) -> None:
            raise ValueError("Test error")

        async def working_callback(bar: Bar) -> None:
            bars_received.append(bar)

        await stream.subscribe(failing_callback)
        await stream.subscribe(working_callback)

        await stream.connect()
        await stream.start()

        # Working callback should still receive all bars despite failing callback
        assert len(bars_received) == 3
