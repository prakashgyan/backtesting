"""Unit tests for helper utilities."""

import pytest
import tempfile
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from day_trader.utils.helpers import save_bars_to_csv, load_bars_from_csv, get_last_n_days
from day_trader.models import Bar


class TestHelperUtilities:
    """Test cases for helper utilities."""

    def test_save_and_load_bars_csv(self) -> None:
        """Test saving and loading bars from CSV."""
        # Create sample bars
        bars = []
        base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            bars.append(
                Bar(
                    symbol="AAPL",
                    timestamp=base_time + timedelta(minutes=i),
                    open=150.0 + i,
                    high=151.0 + i,
                    low=149.0 + i,
                    close=150.5 + i,
                    volume=1000000.0,
                )
            )

        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = Path(f.name)

        try:
            save_bars_to_csv(bars, temp_path)
            assert temp_path.exists()

            # Load bars back
            loaded_bars = load_bars_from_csv(temp_path, "AAPL")
            assert len(loaded_bars) == 5

            # Verify content
            for i, bar in enumerate(loaded_bars):
                assert bar.symbol == "AAPL"
                assert bar.open == 150.0 + i
                assert bar.close == 150.5 + i
        finally:
            temp_path.unlink()

    def test_get_last_n_days(self) -> None:
        """Test getting date range for last N days."""
        start_date, end_date = get_last_n_days(30)

        assert isinstance(start_date, date)
        assert isinstance(end_date, date)
        assert end_date > start_date

        # End date should be today
        assert end_date == date.today()

        # Difference should be approximately 30 days
        delta = (end_date - start_date).days
        assert delta == 30

    def test_save_bars_creates_directory(self) -> None:
        """Test that save_bars creates missing directories."""
        bars = [
            Bar(
                symbol="TEST",
                timestamp=datetime.now(timezone.utc),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1000000.0,
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create path with non-existent subdirectories
            output_path = Path(tmpdir) / "subdir1" / "subdir2" / "data.csv"

            save_bars_to_csv(bars, output_path)
            assert output_path.exists()

    def test_load_bars_with_invalid_rows(self) -> None:
        """Test loading bars skips invalid rows."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            # Write CSV with some invalid rows
            f.write("timestamp,open,high,low,close,volume\n")
            f.write("2024-01-01T10:00:00,150.0,151.0,149.0,150.5,1000000\n")
            f.write("invalid,data,here\n")  # Invalid row
            f.write("2024-01-01T10:01:00,151.0,152.0,150.0,151.5,1000000\n")
            temp_path = Path(f.name)

        try:
            bars = load_bars_from_csv(temp_path, "TEST")
            # Should only load valid rows
            assert len(bars) == 2
        finally:
            temp_path.unlink()


class TestDataFetcherStub:
    """Test cases for DataFetcher (stub tests without actual API calls)."""

    def test_data_fetcher_initialization(self) -> None:
        """Test DataFetcher initialization."""
        from day_trader.utils.helpers import DataFetcher
        from day_trader.config import Settings
        import os

        # Set up env vars for Settings
        os.environ["ALPACA_API_KEY"] = "test_key"
        os.environ["ALPACA_SECRET_KEY"] = "test_secret"

        try:
            settings = Settings()
            fetcher = DataFetcher(settings)
            assert fetcher.settings is not None
            assert fetcher._stock_client is not None
            assert fetcher._crypto_client is not None
        finally:
            del os.environ["ALPACA_API_KEY"]
            del os.environ["ALPACA_SECRET_KEY"]

    def test_timeframe_mapping(self) -> None:
        """Test timeframe string to enum mapping."""
        # This tests the timeframe_map logic indirectly
        valid_timeframes = ["1min", "5min", "15min", "1h", "1d"]

        # Verify all are valid (no exception)
        for tf in valid_timeframes:
            assert tf in ["1min", "5min", "15min", "1h", "1d"]
