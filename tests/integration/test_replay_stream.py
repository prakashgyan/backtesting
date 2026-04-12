"""Integration tests for replay data stream."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

from day_trader.data.replay import ReplayStream
from day_trader.models import Bar


@pytest.fixture
def sample_bars_list() -> list[Bar]:
    """Create a list of sample bars."""
    bars = []
    base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(10):
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
    return bars


@pytest.fixture
def csv_file_with_bars(sample_bars_list: list[Bar]) -> Path:
    """Create a temporary CSV file with sample bars."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        # Write header
        f.write("timestamp,open,high,low,close,volume\n")

        # Write bars
        for bar in sample_bars_list:
            f.write(
                f"{bar.timestamp.isoformat()},{bar.open},{bar.high},"
                f"{bar.low},{bar.close},{bar.volume}\n"
            )

        return Path(f.name)


class TestReplayStream:
    """Test cases for ReplayStream."""

    @pytest.mark.asyncio
    async def test_replay_initialization(self, sample_bars_list: list[Bar]) -> None:
        """Test replay stream initialization."""
        stream = ReplayStream(sample_bars_list, speed=1.0)
        assert len(stream.bars) == 10
        assert stream.speed == 1.0

    @pytest.mark.asyncio
    async def test_replay_connect_disconnect(self, sample_bars_list: list[Bar]) -> None:
        """Test connecting and disconnecting."""
        stream = ReplayStream(sample_bars_list)

        assert not stream.connected
        await stream.connect()
        assert stream.connected

        await stream.disconnect()
        assert not stream.connected

    @pytest.mark.asyncio
    async def test_replay_with_bars(self, sample_bars_list: list[Bar]) -> None:
        """Test replaying bars."""
        stream = ReplayStream(sample_bars_list, speed=100.0)  # Fast speed
        bars_received = []

        async def on_bar(bar: Bar) -> None:
            bars_received.append(bar)

        await stream.subscribe(on_bar)
        await stream.connect()
        await stream.start()

        assert len(bars_received) == 10
        assert bars_received[0].symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_replay_from_csv(self, csv_file_with_bars: Path) -> None:
        """Test loading and replaying from CSV."""
        stream = ReplayStream.from_csv(csv_file_with_bars, "AAPL")
        stream.set_speed(100.0)
        assert len(stream.bars) == 10

        bars_received = []

        async def on_bar(bar: Bar) -> None:
            bars_received.append(bar)

        await stream.subscribe(on_bar)
        await stream.connect()
        await stream.start()

        assert len(bars_received) == 10
        assert bars_received[0].open == 150.0
        assert bars_received[-1].close >= 155.0

    @pytest.mark.asyncio
    async def test_replay_speed_adjustment(self, sample_bars_list: list[Bar]) -> None:
        """Test speed adjustment."""
        stream = ReplayStream(sample_bars_list)

        stream.set_speed(10.0)
        assert stream.speed == 10.0

        with pytest.raises(ValueError):
            stream.set_speed(-1.0)

    @pytest.mark.asyncio
    async def test_replay_progress(self, sample_bars_list: list[Bar]) -> None:
        """Test progress tracking."""
        stream = ReplayStream(sample_bars_list, speed=100.0)

        await stream.connect()

        # Check progress before and during replay
        assert stream.progress == 0.0

        # Run replay
        await stream.start()

        # After completion
        assert stream.progress == 100.0

    @pytest.mark.asyncio
    async def test_replay_empty_bars(self) -> None:
        """Test replay with no bars."""
        stream = ReplayStream([])

        with pytest.raises(Exception):
            await stream.connect()

    @pytest.mark.asyncio
    async def test_replay_stop(self, sample_bars_list: list[Bar]) -> None:
        """Test stopping replay."""
        stream = ReplayStream(sample_bars_list)
        bars_received = []

        async def on_bar(bar: Bar) -> None:
            bars_received.append(bar)
            if len(bars_received) == 5:
                # Stop after 5 bars
                await stream.stop()

        await stream.subscribe(on_bar)
        await stream.connect()
        await stream.start()

        # Should have stopped early
        assert len(bars_received) == 5

    @pytest.mark.asyncio
    async def test_replay_progress_callback(self, sample_bars_list: list[Bar]) -> None:
        """Test optional progress callback receives replay updates."""
        stream = ReplayStream(sample_bars_list, speed=100.0)
        updates: list[tuple[int, int]] = []

        def on_progress(current: int, total: int) -> None:
            updates.append((current, total))

        stream.set_progress_callback(on_progress)

        await stream.connect()
        await stream.start()

        assert updates
        assert updates[0] == (0, len(sample_bars_list))
        assert updates[-1] == (len(sample_bars_list), len(sample_bars_list))
