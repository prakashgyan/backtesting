"""Base interfaces and abstract classes for the trading system."""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, List, Optional

from day_trader.models import AccountInfo, Bar, Order, Position


class DataStreamInterface(ABC):
    """Abstract base class for data stream implementations.

    Defines the contract for any data source (live or replay).
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to data source."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to data source."""
        pass

    @abstractmethod
    async def subscribe(self, callback: Callable[[Bar], Awaitable[None]]) -> None:
        """Subscribe to bar updates.

        Args:
            callback: Async function called with each bar
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start emitting bars."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop emitting bars."""
        pass


class OrderBrokerInterface(ABC):
    """Narrow interface for order placement only.

    Use this when a component only needs to place buy/sell orders
    and should not depend on account query capabilities.
    """

    @abstractmethod
    async def buy(
        self, symbol: str, qty: float, limit_price: float | None = None
    ) -> Order:
        """Place a buy order.

        Args:
            symbol: Stock ticker symbol
            qty: Quantity to buy
            limit_price: Optional limit price (market order if None)

        Returns:
            Order confirmation

        Raises:
            OrderError: If order placement fails
        """
        pass

    @abstractmethod
    async def sell(
        self, symbol: str, qty: float, limit_price: float | None = None
    ) -> Order:
        """Place a sell order.

        Args:
            symbol: Stock ticker symbol
            qty: Quantity to sell
            limit_price: Optional limit price (market order if None)

        Returns:
            Order confirmation

        Raises:
            OrderError: If order placement fails
        """
        pass


class AccountQueryInterface(ABC):
    """Narrow interface for account and position queries only.

    Use this when a component only needs to read account state
    and should not depend on order placement capabilities.
    """

    @abstractmethod
    async def get_account(self) -> AccountInfo:
        """Retrieve current account information.

        Returns:
            AccountInfo with cash, buying power, portfolio value

        Raises:
            BrokerError: If account retrieval fails
        """
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Retrieve all open positions.

        Returns:
            List of Position objects

        Raises:
            BrokerError: If position retrieval fails
        """
        pass

    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        """Retrieve position for a specific symbol.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Position object or None if not held

        Raises:
            BrokerError: If position retrieval fails
        """
        pass


class BrokerInterface(OrderBrokerInterface, AccountQueryInterface):
    """Full broker interface combining order placement and account queries.

    Existing broker implementations (AlpacaBroker, SimulatedBroker) implement
    this combined interface unchanged. Components that only need a subset of
    broker capabilities should depend on the narrower interfaces above.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to broker."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to broker."""
        pass


class StrategyInterface(ABC):
    """Abstract base class for strategy implementations.

    Defines the contract for custom trading strategies.
    """

    @property
    @abstractmethod
    def executed_orders(self) -> List[Order]:
        """Return all orders executed by this strategy during the run.

        The Engine reads this list at shutdown to compute metrics.
        Implementations must maintain it as orders are filled.
        """
        ...

    def attach_run_tracker(self, run_tracker: object, run_id: str) -> None:
        """Attach a per-run event store so the strategy can persist order events.

        The Engine calls this after starting the run tracker and before
        calling initialize(). The default implementation is a no-op — override
        in Strategy base class or concrete strategies that want persistence.

        Args:
            run_tracker: EventStoreInterface implementation
            run_id: Unique identifier for this run
        """

    @abstractmethod
    async def initialize(self, broker: BrokerInterface) -> None:
        """Initialize strategy with broker reference.

        Called once at engine startup.

        Args:
            broker: BrokerInterface for placing orders

        Raises:
            StrategyError: If initialization fails
        """
        pass

    @abstractmethod
    async def on_bar(self, bar: Bar) -> None:
        """Called when a new bar is received.

        This is where the strategy logic runs. Strategy should call
        broker.buy() or broker.sell() to place orders.

        Args:
            bar: The bar data

        Raises:
            StrategyError: If strategy execution fails
        """
        pass

    @abstractmethod
    async def finalize(self) -> None:
        """Clean up and close positions.

        Called once when engine is shutting down.

        Raises:
            StrategyError: If finalization fails
        """
        pass
