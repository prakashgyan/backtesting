"""Base strategy class for user-defined strategies."""

from abc import abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

import dataclasses

from day_trader.config import RunDefaults
from day_trader.core.base import BrokerInterface, StrategyInterface
from day_trader.core.exceptions import StrategyError
from day_trader.logging import get_logger
from day_trader.models import Bar, Order

if TYPE_CHECKING:
    from day_trader.run_tracking import EventStoreInterface

logger = get_logger(__name__)


class Strategy(StrategyInterface):
    """Base class for trading strategies.

    Subclasses should override on_bar() to implement trading logic.

    Example:
        class MyStrategy(Strategy):
            async def on_bar(self, bar: Bar) -> None:
                if bar.close > 150:
                    await self.buy("AAPL", qty=10)
    """

    def __init__(self) -> None:
        """Initialize strategy."""
        self.broker: Optional[BrokerInterface] = None
        self._signal: Optional[str] = None
        self._trades_executed = 0
        self._executed_orders: list[Order] = []
        self._run_tracker: Optional["EventStoreInterface"] = None
        self._run_id: Optional[str] = None
        self._current_bar_time: Optional[datetime] = None
        self._logger = get_logger(f"strategy.{self.__class__.__name__}")

    async def initialize(self, broker: BrokerInterface) -> None:
        """Initialize strategy with broker reference.

        Called once at engine startup. Override to set up indicators,
        state, or initial data.

        Args:
            broker: Broker interface for placing orders
        """
        self.broker = broker
        self._logger.info(f"{self.__class__.__name__} initialized")

    def runtime_defaults(self) -> dict[str, Any]:
        """Optional run-time defaults consumed by the CLI.

        Strategies can override this to define preferred defaults such as:
        - symbol
        - mode
        - days
        - speed
        - timeframe

        Returns:
            Dict of run parameter defaults.
        """
        return dataclasses.asdict(RunDefaults())

    @abstractmethod
    async def on_bar(self, bar: Bar) -> None:
        """Process incoming bar and generate trading signals.

        This is called for each bar received from the data stream.
        Strategy should call self.buy() or self.sell() to place orders.

        Args:
            bar: Market data bar

        Raises:
            StrategyError: If strategy logic fails
        """
        ...

    async def finalize(self) -> None:
        """Clean up and close positions.

        Called once when engine is shutting down. Override to
        close positions, save state, or log results.
        """
        self._logger.info(f"Strategy finalized. Trades executed: {self._trades_executed}")

    def attach_run_tracker(self, run_tracker: "EventStoreInterface", run_id: str) -> None:
        """Attach per-run tracker to persist strategy events."""
        self._run_tracker = run_tracker
        self._run_id = run_id

    def set_current_bar_time(self, bar_time: Optional[datetime]) -> None:
        """Set the current bar timestamp for event logging.
        
        In replay mode, this is called by the engine before each on_bar()
        to ensure events are logged with simulated timestamps.
        """
        self._current_bar_time = bar_time

    async def buy(
        self,
        symbol: str,
        qty: float,
        limit_price: Optional[float] = None,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> Order:
        """Place a buy order.

        Args:
            symbol: Stock ticker symbol
            qty: Quantity to buy
            limit_price: Optional limit price
            reason: Optional strategy-provided explanation for this request
            details: Optional structured context for downstream analysis

        Raises:
            StrategyError: If order placement fails
        """
        if not self.broker:
            raise StrategyError("Broker not initialized")

        try:
            if self._run_tracker:
                self._run_tracker.log_order_request(
                    symbol=symbol,
                    side="BUY",
                    qty=qty,
                    limit_price=limit_price,
                    reason=reason,
                    details=details,
                    event_time=self._current_bar_time,
                )
            order = await self.broker.buy(symbol, qty, limit_price)
            self._trades_executed += 1
            self._executed_orders.append(order)
            if self._run_tracker:
                self._run_tracker.log_order_result(
                    order=order,
                    reason=reason,
                    details=details,
                    event_time=self._current_bar_time,
                )
            self._logger.info(
                "BUY order: %s x%s @ %s%s",
                symbol,
                qty,
                limit_price,
                f" reason={reason}" if reason else "",
            )
            return order
        except Exception as e:
            if self._run_tracker:
                self._run_tracker.log_order_error(
                    symbol=symbol,
                    side="BUY",
                    qty=qty,
                    limit_price=limit_price,
                    error=str(e),
                    reason=reason,
                    details=details,
                    event_time=self._current_bar_time,
                )
            raise StrategyError(f"Buy order failed: {e}") from e

    async def sell(
        self,
        symbol: str,
        qty: float,
        limit_price: Optional[float] = None,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> Order:
        """Place a sell order.

        Args:
            symbol: Stock ticker symbol
            qty: Quantity to sell
            limit_price: Optional limit price
            reason: Optional strategy-provided explanation for this request
            details: Optional structured context for downstream analysis

        Raises:
            StrategyError: If order placement fails
        """
        if not self.broker:
            raise StrategyError("Broker not initialized")

        try:
            if self._run_tracker:
                self._run_tracker.log_order_request(
                    symbol=symbol,
                    side="SELL",
                    qty=qty,
                    limit_price=limit_price,
                    reason=reason,
                    details=details,
                    event_time=self._current_bar_time,
                )
            order = await self.broker.sell(symbol, qty, limit_price)
            self._trades_executed += 1
            self._executed_orders.append(order)
            if self._run_tracker:
                self._run_tracker.log_order_result(
                    order=order,
                    reason=reason,
                    details=details,
                    event_time=self._current_bar_time,
                )
            self._logger.info(
                "SELL order: %s x%s @ %s%s",
                symbol,
                qty,
                limit_price,
                f" reason={reason}" if reason else "",
            )
            return order
        except Exception as e:
            if self._run_tracker:
                self._run_tracker.log_order_error(
                    symbol=symbol,
                    side="SELL",
                    qty=qty,
                    limit_price=limit_price,
                    error=str(e),
                    reason=reason,
                    details=details,
                    event_time=self._current_bar_time,
                )
            raise StrategyError(f"Sell order failed: {e}") from e

    @property
    def signal(self) -> Optional[str]:
        """Get current trading signal (BUY, SELL, or None)."""
        return self._signal

    @signal.setter
    def signal(self, value: Optional[str]) -> None:
        """Set trading signal."""
        if value not in ("BUY", "SELL", None):
            raise ValueError(f"Invalid signal: {value}")
        self._signal = value

    @property
    def executed_orders(self) -> list[Order]:
        """Get executed orders captured by this strategy."""
        return self._executed_orders
