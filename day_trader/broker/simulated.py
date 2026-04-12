"""Simulated broker for replay/backtest mode. No real orders are placed."""

import dataclasses
from datetime import datetime, timezone
from typing import Dict, List, Optional

from day_trader.broker.base import BrokerBase
from day_trader.core.exceptions import BrokerError, OrderError
from day_trader.logging import get_logger
from day_trader.models import AccountInfo, Order, OrderSide, OrderStatus, Position

logger = get_logger(__name__)


class SimulatedBroker(BrokerBase):
    """Simulated broker that tracks positions and orders locally.

    Used for replay/backtest mode. No API calls are made.
    """

    def __init__(self, initial_cash: float = 100000.0) -> None:
        super().__init__()
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._positions: Dict[str, Position] = {}
        self._orders: List[Order] = []

    async def connect(self) -> None:
        self._connected = True
        logger.info(f"Simulated broker ready (cash: ${self._cash:,.2f})")

    async def disconnect(self) -> None:
        self._connected = False

    async def get_account(self) -> AccountInfo:
        portfolio_value = self._cash + sum(
            p.qty * p.current_price for p in self._positions.values()
        )
        return AccountInfo(
            cash=self._cash,
            buying_power=self._cash,
            portfolio_value=max(portfolio_value, 0.01),
            equity=portfolio_value,
        )

    async def buy(self, symbol: str, qty: float, limit_price: Optional[float] = None) -> Order:
        price = limit_price or 0.0
        if price <= 0:
            raise OrderError("Simulated broker requires a limit_price for buy orders")

        cost = price * qty
        if cost > self._cash:
            raise OrderError(f"Insufficient cash: need ${cost:,.2f}, have ${self._cash:,.2f}")

        self._cash -= cost

        # Update or create position
        if symbol in self._positions:
            pos = self._positions[symbol]
            total_qty = pos.qty + qty
            new_avg = ((pos.avg_fill_price * pos.qty) + (price * qty)) / total_qty
            self._positions[symbol] = dataclasses.replace(
                pos, qty=total_qty, avg_fill_price=new_avg, current_price=price
            )
        else:
            self._positions[symbol] = Position(
                symbol=symbol, qty=qty, avg_fill_price=price, current_price=price
            )

        order = Order(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            filled_qty=qty,
            avg_fill_price=price,
            filled_at=datetime.now(timezone.utc),
        )
        self._orders.append(order)
        logger.info(f"[SIM] BUY {symbol} x{qty} @ ${price:,.2f}")
        return order

    async def sell(self, symbol: str, qty: float, limit_price: Optional[float] = None) -> Order:
        price = limit_price or 0.0
        if price <= 0:
            raise OrderError("Simulated broker requires a limit_price for sell orders")

        if symbol not in self._positions or self._positions[symbol].qty < qty:
            held = self._positions[symbol].qty if symbol in self._positions else 0
            raise OrderError(f"Insufficient position: need {qty}, have {held}")

        self._cash += price * qty

        pos = self._positions[symbol]
        new_qty = pos.qty - qty
        if new_qty == 0:
            del self._positions[symbol]
        else:
            self._positions[symbol] = dataclasses.replace(pos, qty=new_qty, current_price=price)

        order = Order(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            filled_qty=qty,
            avg_fill_price=price,
            filled_at=datetime.now(timezone.utc),
        )
        self._orders.append(order)
        logger.info(f"[SIM] SELL {symbol} x{qty} @ ${price:,.2f}")
        return order

    async def get_positions(self) -> List[Position]:
        return list(self._positions.values())

    async def get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)
