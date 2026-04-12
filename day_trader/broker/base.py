"""Broker base implementation with connection management."""

from typing import Optional

from day_trader.core.base import BrokerInterface
from day_trader.core.exceptions import BrokerError
from day_trader.logging import get_logger

logger = get_logger(__name__)


class BrokerBase(BrokerInterface):
    """Base broker implementation with common connection management.

    Subclasses should override API-specific methods.
    """

    def __init__(self) -> None:
        """Initialize broker."""
        self._connected = False
        self._client: Optional[object] = None

    @property
    def connected(self) -> bool:
        """Check if broker is connected."""
        return self._connected

    async def connect(self) -> None:
        """Establish connection to broker.

        Must be overridden by subclasses.

        Raises:
            BrokerError: If connection fails
        """
        raise NotImplementedError("Subclasses must implement connect()")

    async def disconnect(self) -> None:
        """Close connection to broker.

        Must be overridden by subclasses.
        """
        raise NotImplementedError("Subclasses must implement disconnect()")
