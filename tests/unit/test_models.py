"""Unit tests for data models."""

import pytest
from datetime import datetime, timezone

from day_trader.models import Bar, Position, Order, OrderSide, OrderStatus, AccountInfo


class TestBar:
    """Test cases for Bar model."""

    def test_bar_creation(self, sample_bar: Bar) -> None:
        """Test creating a valid bar."""
        assert sample_bar.symbol == "AAPL"
        assert sample_bar.close == 151.0
        assert sample_bar.volume > 0

    def test_bar_invalid_ohlc(self) -> None:
        """Test that bar rejects invalid OHLC values."""
        with pytest.raises(ValueError, match="OHLC prices must be positive"):
            Bar(
                symbol="AAPL",
                timestamp=datetime.now(timezone.utc),
                open=-150.0,
                high=152.0,
                low=149.0,
                close=151.0,
                volume=1000000.0,
            )

    def test_bar_high_low_validation(self) -> None:
        """Test that high >= low validation works."""
        with pytest.raises(ValueError, match="High price must be >= low price"):
            Bar(
                symbol="AAPL",
                timestamp=datetime.now(timezone.utc),
                open=150.0,
                high=148.0,
                low=149.0,
                close=151.0,
                volume=1000000.0,
            )

    def test_bar_negative_volume(self) -> None:
        """Test that bar rejects negative volume."""
        with pytest.raises(ValueError, match="Volume cannot be negative"):
            Bar(
                symbol="AAPL",
                timestamp=datetime.now(timezone.utc),
                open=150.0,
                high=152.0,
                low=149.0,
                close=151.0,
                volume=-1000.0,
            )

    def test_price_change_pct(self, sample_bar: Bar) -> None:
        """Test price change percentage calculation."""
        # open=150, close=151
        pct = sample_bar.price_change_pct()
        assert abs(pct - 0.6667) < 0.01

    def test_mid_price(self, sample_bar: Bar) -> None:
        """Test mid-price calculation."""
        # high=152, low=149
        mid = sample_bar.mid_price()
        assert mid == 150.5


class TestPosition:
    """Test cases for Position model."""

    def test_position_creation(self, sample_position: Position) -> None:
        """Test creating a valid position."""
        assert sample_position.symbol == "AAPL"
        assert sample_position.qty == 100.0

    def test_position_invalid_price(self) -> None:
        """Test that position rejects invalid prices."""
        with pytest.raises(ValueError, match="Prices must be positive"):
            Position(
                symbol="AAPL",
                qty=100.0,
                avg_fill_price=-150.0,
                current_price=151.0,
            )

    def test_unrealized_pnl(self, sample_position: Position) -> None:
        """Test unrealized P&L calculation."""
        # 100 shares * (151 - 150) = 100
        pnl = sample_position.unrealized_pnl()
        assert pnl == 100.0

    def test_unrealized_pnl_pct(self, sample_position: Position) -> None:
        """Test unrealized P&L percentage calculation."""
        # (151 - 150) / 150 * 100 = 0.667%
        pnl_pct = sample_position.unrealized_pnl_pct()
        assert abs(pnl_pct - 0.6667) < 0.01


class TestOrder:
    """Test cases for Order model."""

    def test_order_creation(self, sample_order: Order) -> None:
        """Test creating a valid order."""
        assert sample_order.symbol == "AAPL"
        assert sample_order.side == OrderSide.BUY

    def test_order_invalid_qty(self) -> None:
        """Test that order rejects invalid quantities."""
        with pytest.raises(ValueError, match="Order quantity must be positive"):
            Order(
                symbol="AAPL",
                qty=-100.0,
                side=OrderSide.BUY,
                status=OrderStatus.PENDING,
            )

    def test_order_filled_qty_exceeds(self) -> None:
        """Test that filled qty cannot exceed order qty."""
        with pytest.raises(ValueError, match="Filled qty cannot exceed order qty"):
            Order(
                symbol="AAPL",
                qty=100.0,
                side=OrderSide.BUY,
                status=OrderStatus.FILLED,
                filled_qty=150.0,
            )

    def test_is_complete(self, sample_order: Order) -> None:
        """Test order completion check."""
        assert sample_order.is_complete()

    def test_is_partial_fill(self) -> None:
        """Test partial fill detection."""
        order = Order(
            symbol="AAPL",
            qty=100.0,
            side=OrderSide.BUY,
            status=OrderStatus.PENDING,
            filled_qty=50.0,
            avg_fill_price=150.0,
        )
        assert order.is_partial_fill()


class TestAccountInfo:
    """Test cases for AccountInfo model."""

    def test_account_creation(self, sample_account_info: AccountInfo) -> None:
        """Test creating valid account info."""
        assert sample_account_info.cash == 10000.0
        assert sample_account_info.portfolio_value == 60000.0

    def test_account_invalid_cash(self) -> None:
        """Test that account rejects negative cash."""
        with pytest.raises(ValueError, match="Cash and buying power cannot be negative"):
            AccountInfo(
                cash=-1000.0,
                buying_power=50000.0,
                portfolio_value=60000.0,
                equity=60000.0,
            )

    def test_margin_usage_pct(self, sample_account_info: AccountInfo) -> None:
        """Test margin usage percentage calculation."""
        # used_margin = 60000 - 10000 = 50000
        # margin_usage = 50000 / 50000 * 100 = 100%
        margin_pct = sample_account_info.margin_usage_pct()
        assert margin_pct == 100.0
