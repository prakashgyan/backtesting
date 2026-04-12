"""Core data models for the trading system."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    """Order side enum."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Order status enum."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Bar:
    """Represents a candlestick bar (OHLCV data).

    Attributes:
        symbol: Stock ticker symbol (e.g., 'AAPL')
        timestamp: When the bar was generated
        open: Opening price
        high: Highest price in the period
        low: Lowest price in the period
        close: Closing price
        volume: Trading volume
    """

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        """Validate bar data."""
        if self.open <= 0 or self.high <= 0 or self.low <= 0 or self.close <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < self.low:
            raise ValueError("High price must be >= low price")
        if self.volume < 0:
            raise ValueError("Volume cannot be negative")
        if self.timestamp.tzinfo is None:
            raise ValueError("Bar timestamp must be timezone-aware (UTC)")

    def price_change_pct(self) -> float:
        """Calculate percentage change from open to close."""
        return ((self.close - self.open) / self.open) * 100

    def mid_price(self) -> float:
        """Calculate mid-price (average of high and low)."""
        return (self.high + self.low) / 2


@dataclass(frozen=True)
class Position:
    """Represents an open position in a symbol.

    Attributes:
        symbol: Stock ticker symbol
        qty: Quantity of shares held
        avg_fill_price: Average fill price of the position
        current_price: Current market price
    """

    symbol: str
    qty: float
    avg_fill_price: float
    current_price: float

    def __post_init__(self) -> None:
        """Validate position data."""
        if self.avg_fill_price <= 0 or self.current_price <= 0:
            raise ValueError("Prices must be positive")

    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L."""
        return (self.current_price - self.avg_fill_price) * self.qty

    def unrealized_pnl_pct(self) -> float:
        """Calculate unrealized P&L percentage."""
        if self.avg_fill_price == 0:
            return 0.0
        return (self.unrealized_pnl() / (self.avg_fill_price * self.qty)) * 100


@dataclass
class Order:
    """Represents a submitted order.

    Attributes:
        symbol: Stock ticker symbol
        qty: Quantity of shares
        side: BUY or SELL
        status: Current order status
        filled_qty: Quantity filled so far
        avg_fill_price: Average price of filled portion
        created_at: When order was created
        filled_at: When order was filled (if applicable)
    """

    symbol: str
    qty: float
    side: OrderSide
    status: OrderStatus
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate order data."""
        if self.qty <= 0:
            raise ValueError("Order quantity must be positive")
        if self.avg_fill_price < 0:
            raise ValueError("Fill price cannot be negative")
        if self.filled_qty > self.qty:
            raise ValueError("Filled qty cannot exceed order qty")
        if self.status == OrderStatus.FILLED:
            if self.filled_qty <= 0:
                raise ValueError("FILLED order must have filled_qty > 0")
            if self.avg_fill_price <= 0:
                raise ValueError("FILLED order must have avg_fill_price > 0")

    def is_complete(self) -> bool:
        """Check if order is complete."""
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)

    def is_partial_fill(self) -> bool:
        """Check if order has partial fill."""
        return 0 < self.filled_qty < self.qty


@dataclass
class AccountInfo:
    """Represents account information.

    Attributes:
        cash: Available cash balance
        buying_power: Buying power available
        portfolio_value: Total portfolio value
        equity: Account equity
        last_updated: When the info was fetched
    """

    cash: float
    buying_power: float
    portfolio_value: float
    equity: float
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Validate account data."""
        if self.cash < 0 or self.buying_power < 0:
            raise ValueError("Cash and buying power cannot be negative")
        if self.portfolio_value <= 0:
            raise ValueError("Portfolio value must be positive")

    def margin_usage_pct(self) -> float:
        """Calculate margin usage percentage."""
        if self.buying_power == 0:
            return 0.0
        used_margin = self.portfolio_value - self.cash
        return (used_margin / self.buying_power) * 100
