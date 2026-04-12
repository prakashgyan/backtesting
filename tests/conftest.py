"""Pytest configuration and fixtures."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from day_trader.config import Settings
from day_trader.models import Bar, Order, OrderSide, OrderStatus, Position, AccountInfo


@pytest.fixture
def temp_config_dir() -> Path:
    """Create a temporary directory for config files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_settings(temp_config_dir: Path) -> Settings:
    """Create mock settings for testing."""
    return Settings(
        alpaca_api_key="test_key",
        alpaca_secret_key="test_secret",
        paper_trading=True,
        log_level="DEBUG",
        data_dir=temp_config_dir / "data",
        logs_dir=temp_config_dir / "logs",
    )


@pytest.fixture
def sample_bar() -> Bar:
    """Create a sample bar for testing."""
    return Bar(
        symbol="AAPL",
        timestamp=datetime.now(timezone.utc),
        open=150.0,
        high=152.0,
        low=149.0,
        close=151.0,
        volume=1000000.0,
    )


@pytest.fixture
def sample_bars() -> list[Bar]:
    """Create a sequence of sample bars simulating price movement."""
    bars = []
    base_price = 150.0
    base_time = datetime.now(timezone.utc)

    for i in range(20):
        price = base_price + (i * 0.5)
        bars.append(
            Bar(
                symbol="AAPL",
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price + 1.0,
                low=price - 0.5,
                close=price + 0.25,
                volume=1000000.0,
            )
        )

    return bars


@pytest.fixture
def sample_position() -> Position:
    """Create a sample position for testing."""
    return Position(
        symbol="AAPL",
        qty=100.0,
        avg_fill_price=150.0,
        current_price=151.0,
    )


@pytest.fixture
def sample_order() -> Order:
    """Create a sample order for testing."""
    return Order(
        symbol="AAPL",
        qty=100.0,
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        filled_qty=100.0,
        avg_fill_price=150.0,
    )


@pytest.fixture
def sample_account_info() -> AccountInfo:
    """Create a sample account info for testing."""
    return AccountInfo(
        cash=10000.0,
        buying_power=50000.0,
        portfolio_value=60000.0,
        equity=60000.0,
    )
