"""Alpaca broker implementation."""

from datetime import datetime
from typing import List, Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide as AlpacaOrderSide, OrderStatus as AlpacaOrderStatus

from day_trader.broker.base import BrokerBase
from day_trader.core.exceptions import BrokerError, AuthenticationError, OrderError
from day_trader.config import Settings
from day_trader.logging import get_logger
from day_trader.models import AccountInfo, Order, OrderSide, OrderStatus, Position

logger = get_logger(__name__)


class AlpacaBroker(BrokerBase):
    """Alpaca broker implementation.

    Handles order placement, position management, and account queries via Alpaca API.
    Uses alpaca-py SDK for REST API interaction.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize Alpaca broker.

        Args:
            settings: Configuration settings with API credentials
        """
        super().__init__()
        self.settings = settings
        self._alpaca_client: Optional[TradingClient] = None

    async def connect(self) -> None:
        """Establish connection to Alpaca API.

        Raises:
            AuthenticationError: If API credentials are invalid
            BrokerError: If connection fails
        """
        try:
            logger.info("Connecting to Alpaca broker")

            # Create Alpaca trading client
            self._alpaca_client = TradingClient(
                api_key=self.settings.alpaca_api_key,
                secret_key=self.settings.alpaca_secret_key,
                paper=self.settings.paper_trading,
            )

            # Verify connection by getting account
            account = self._alpaca_client.get_account()

            paper_trading = self.settings.paper_trading
            logger.info(
                f"Connected to Alpaca - Mode: {'PAPER' if paper_trading else 'LIVE'}, "
                f"Account: {account.account_number}"
            )

            self._connected = True
            logger.debug("Alpaca broker connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            self._connected = False
            raise AuthenticationError(f"Could not authenticate with Alpaca: {e}")

    async def disconnect(self) -> None:
        """Close connection to Alpaca broker."""
        if self._connected:
            self._alpaca_client = None
            self._connected = False
            logger.info("Alpaca broker disconnected")

    async def get_account(self) -> AccountInfo:
        """Get current account information.

        Returns:
            AccountInfo with cash, buying power, and portfolio value

        Raises:
            BrokerError: If account retrieval fails
        """
        if not self._alpaca_client:
            raise BrokerError("Broker not connected")

        try:
            logger.debug("Fetching account information from Alpaca")
            account = self._alpaca_client.get_account()

            return AccountInfo(
                cash=float(account.cash),
                buying_power=float(account.buying_power),
                portfolio_value=float(account.portfolio_value),
                equity=float(account.equity),
            )
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise BrokerError(f"Could not retrieve account information: {e}")

    async def buy(
        self, symbol: str, qty: float, limit_price: Optional[float] = None
    ) -> Order:
        """Place a buy order.

        Args:
            symbol: Stock ticker symbol
            qty: Quantity to buy
            limit_price: Optional limit price for limit order (market order if None)

        Returns:
            Order confirmation

        Raises:
            OrderError: If order placement fails
        """
        if not self._alpaca_client:
            raise OrderError("Broker not connected")

        try:
            logger.info(
                f"Placing BUY order: {symbol} x{qty} "
                f"{'at limit ' + str(limit_price) if limit_price else 'at market'}"
            )

            # Create order request
            if limit_price:
                order_request = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=AlpacaOrderSide.BUY,
                    limit_price=limit_price,
                    time_in_force="day",
                )
            else:
                order_request = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=AlpacaOrderSide.BUY,
                    time_in_force="day",
                )

            # Submit order
            alpaca_order = self._alpaca_client.submit_order(order_request)

            # Convert to internal Order model
            order = self._convert_alpaca_order(alpaca_order)
            logger.debug(f"Order placed successfully: {alpaca_order.id}")
            return order
        except Exception as e:
            logger.error(f"Failed to place BUY order for {symbol}: {e}")
            raise OrderError(f"Could not place buy order: {e}")

    async def sell(
        self, symbol: str, qty: float, limit_price: Optional[float] = None
    ) -> Order:
        """Place a sell order.

        Args:
            symbol: Stock ticker symbol
            qty: Quantity to sell
            limit_price: Optional limit price for limit order (market order if None)

        Returns:
            Order confirmation

        Raises:
            OrderError: If order placement fails
        """
        if not self._alpaca_client:
            raise OrderError("Broker not connected")

        try:
            logger.info(
                f"Placing SELL order: {symbol} x{qty} "
                f"{'at limit ' + str(limit_price) if limit_price else 'at market'}"
            )

            # Create order request
            if limit_price:
                order_request = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=AlpacaOrderSide.SELL,
                    limit_price=limit_price,
                    time_in_force="day",
                )
            else:
                order_request = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=AlpacaOrderSide.SELL,
                    time_in_force="day",
                )

            # Submit order
            alpaca_order = self._alpaca_client.submit_order(order_request)

            # Convert to internal Order model
            order = self._convert_alpaca_order(alpaca_order)
            logger.debug(f"Order placed successfully: {alpaca_order.id}")
            return order
        except Exception as e:
            logger.error(f"Failed to place SELL order for {symbol}: {e}")
            raise OrderError(f"Could not place sell order: {e}")

    async def get_positions(self) -> List[Position]:
        """Get all open positions.

        Returns:
            List of open Position objects

        Raises:
            BrokerError: If position retrieval fails
        """
        if not self._alpaca_client:
            raise BrokerError("Broker not connected")

        try:
            logger.debug("Fetching all positions from Alpaca")
            alpaca_positions = self._alpaca_client.get_all_positions()

            positions = [self._convert_alpaca_position(p) for p in alpaca_positions]
            logger.debug(f"Found {len(positions)} open positions")
            return positions
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            raise BrokerError(f"Could not retrieve positions: {e}")

    async def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a specific symbol.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Position object or None if no position exists

        Raises:
            BrokerError: If position retrieval fails
        """
        if not self._alpaca_client:
            raise BrokerError("Broker not connected")

        try:
            logger.debug(f"Fetching position for {symbol}")
            alpaca_position = self._alpaca_client.get_open_position(symbol)

            if alpaca_position:
                return self._convert_alpaca_position(alpaca_position)
            return None
        except Exception as e:
            logger.error(f"Failed to get position for {symbol}: {e}")
            raise BrokerError(f"Could not retrieve position: {e}")

    def _convert_alpaca_order(self, alpaca_order) -> Order:
        """Convert Alpaca order to internal Order model.

        Args:
            alpaca_order: Alpaca API order object

        Returns:
            Internal Order model
        """
        # Map Alpaca order status to internal status
        status_map = {
            AlpacaOrderStatus.PENDING_NEW: OrderStatus.PENDING,
            AlpacaOrderStatus.ACCEPTED: OrderStatus.PENDING,
            AlpacaOrderStatus.PENDING_CANCEL: OrderStatus.PENDING,
            AlpacaOrderStatus.CANCELED: OrderStatus.CANCELLED,
            AlpacaOrderStatus.EXPIRED: OrderStatus.CANCELLED,
            AlpacaOrderStatus.FILLED: OrderStatus.FILLED,
            AlpacaOrderStatus.PARTIALLY_FILLED: OrderStatus.FILLED,
            AlpacaOrderStatus.REJECTED: OrderStatus.REJECTED,
        }

        status = status_map.get(alpaca_order.status, OrderStatus.PENDING)

        # Map Alpaca side to internal side
        side = OrderSide.BUY if alpaca_order.side == AlpacaOrderSide.BUY else OrderSide.SELL

        return Order(
            symbol=alpaca_order.symbol,
            qty=float(alpaca_order.qty),
            side=side,
            status=status,
            filled_qty=float(alpaca_order.filled_qty),
            avg_fill_price=float(alpaca_order.filled_avg_price or 0),
            created_at=alpaca_order.created_at,
            filled_at=alpaca_order.filled_at,
        )

    def _convert_alpaca_position(self, alpaca_position) -> Position:
        """Convert Alpaca position to internal Position model.

        Args:
            alpaca_position: Alpaca API position object

        Returns:
            Internal Position model
        """
        return Position(
            symbol=alpaca_position.symbol,
            qty=float(alpaca_position.qty),
            avg_fill_price=float(alpaca_position.avg_fill_price),
            current_price=float(alpaca_position.current_price),
        )
