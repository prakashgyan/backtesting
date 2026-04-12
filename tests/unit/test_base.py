"""Unit tests for exceptions and base classes."""

import pytest
from abc import ABC

from day_trader.core.exceptions import (
    DayTraderException,
    ConfigError,
    DataStreamError,
    BrokerError,
    StrategyError,
    EngineError,
    OrderError,
    AuthenticationError,
    StreamConnectionError,
)
from day_trader.core.base import DataStreamInterface, BrokerInterface, StrategyInterface
from day_trader.models import Bar, AccountInfo, Order, OrderSide, OrderStatus
from datetime import datetime, timezone
from typing import List


class TestExceptions:
    """Test cases for exception hierarchy."""

    def test_exception_inheritance(self) -> None:
        """Test that custom exceptions inherit from base."""
        assert issubclass(ConfigError, DayTraderException)
        assert issubclass(DataStreamError, DayTraderException)
        assert issubclass(BrokerError, DayTraderException)
        assert issubclass(StrategyError, DayTraderException)
        assert issubclass(EngineError, DayTraderException)

    def test_exception_subclass_inheritance(self) -> None:
        """Test that specific exceptions inherit from parent categories."""
        assert issubclass(OrderError, BrokerError)
        assert issubclass(AuthenticationError, BrokerError)
        assert issubclass(StreamConnectionError, DataStreamError)

    def test_raise_custom_exception(self) -> None:
        """Test raising a custom exception."""
        with pytest.raises(ConfigError):
            raise ConfigError("Invalid configuration")

    def test_exception_message_preservation(self) -> None:
        """Test that exception messages are preserved."""
        msg = "Test error message"
        with pytest.raises(BrokerError, match=msg):
            raise BrokerError(msg)


class TestDataStreamInterface:
    """Test cases for DataStreamInterface."""

    def test_interface_is_abstract(self) -> None:
        """Test that DataStreamInterface cannot be instantiated."""
        with pytest.raises(TypeError):
            DataStreamInterface()

    def test_interface_requires_methods(self) -> None:
        """Test that concrete implementation must implement all methods."""

        class IncompleteStream(DataStreamInterface):
            async def connect(self) -> None:
                pass

        with pytest.raises(TypeError):
            IncompleteStream()

    def test_complete_implementation(self) -> None:
        """Test that complete implementation can be instantiated."""

        class CompleteStream(DataStreamInterface):
            async def connect(self) -> None:
                pass

            async def disconnect(self) -> None:
                pass

            async def subscribe(self, callback) -> None:
                pass

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        stream = CompleteStream()
        assert isinstance(stream, DataStreamInterface)


class TestBrokerInterface:
    """Test cases for BrokerInterface."""

    def test_interface_is_abstract(self) -> None:
        """Test that BrokerInterface cannot be instantiated."""
        with pytest.raises(TypeError):
            BrokerInterface()

    def test_complete_implementation(self) -> None:
        """Test that complete implementation can be instantiated."""

        class CompleteBroker(BrokerInterface):
            async def connect(self) -> None:
                pass

            async def disconnect(self) -> None:
                pass

            async def get_account(self) -> AccountInfo:
                return AccountInfo(
                    cash=10000.0,
                    buying_power=50000.0,
                    portfolio_value=60000.0,
                    equity=60000.0,
                )

            async def buy(self, symbol: str, qty: float, limit_price: float = None) -> Order:
                return Order(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY,
                    status=OrderStatus.FILLED,
                    filled_qty=qty,
                    avg_fill_price=150.0,
                )

            async def sell(self, symbol: str, qty: float, limit_price: float = None) -> Order:
                return Order(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.SELL,
                    status=OrderStatus.FILLED,
                    filled_qty=qty,
                    avg_fill_price=150.0,
                )

            async def get_positions(self):
                return []

            async def get_position(self, symbol: str):
                return None

        broker = CompleteBroker()
        assert isinstance(broker, BrokerInterface)


class TestStrategyInterface:
    """Test cases for StrategyInterface."""

    def test_interface_is_abstract(self) -> None:
        """Test that StrategyInterface cannot be instantiated."""
        with pytest.raises(TypeError):
            StrategyInterface()

    def test_complete_implementation(self) -> None:
        """Test that complete implementation can be instantiated."""

        class CompleteStrategy(StrategyInterface):
            @property
            def executed_orders(self) -> List[Order]:
                return []

            async def initialize(self, broker) -> None:
                pass

            async def on_bar(self, bar: Bar) -> None:
                pass

            async def finalize(self) -> None:
                pass

        strategy = CompleteStrategy()
        assert isinstance(strategy, StrategyInterface)
