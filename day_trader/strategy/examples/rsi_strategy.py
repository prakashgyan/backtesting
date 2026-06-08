"""RSI (Relative Strength Index) strategy example."""

from collections import deque
from typing import Any, Optional

from day_trader.core.exceptions import BrokerError
from day_trader.models import Bar
from day_trader.strategy.base import Strategy


class RSIStrategy(Strategy):
    """Relative Strength Index (RSI) Strategy.

    Signals:
    - BUY when RSI < 30 (oversold)
    - SELL when RSI > 70 (overbought)

    RSI = 100 - (100 / (1 + RS))
    Where RS = Average Gain / Average Loss over period
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        order_qty: float = 10.0,
    ):
        """Initialize RSI strategy.

        Args:
            period: RSI period (default: 14)
            oversold: Oversold threshold (default: 30)
            overbought: Overbought threshold (default: 70)
            order_qty: Shares per signal order (default: 10)
        """
        super().__init__()

        if period < 2:
            raise ValueError("period must be >= 2")
        if not 0 <= oversold <= 100:
            raise ValueError("oversold must be between 0 and 100")
        if not 0 <= overbought <= 100:
            raise ValueError("overbought must be between 0 and 100")
        if oversold >= overbought:
            raise ValueError("oversold must be less than overbought")
        if order_qty <= 0:
            raise ValueError("order_qty must be > 0")

        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.order_qty = order_qty

        # Backward-compatible single-series buffers used by tests.
        self.prices: deque = deque(maxlen=period + 1)
        self.gains: deque = deque(maxlen=period)
        self.losses: deque = deque(maxlen=period)
        self.bars_count = 0
        self.previous_rsi: Optional[float] = None

        # Per-symbol state for multi-symbol streams.
        self._symbol_state: dict[str, dict] = {}
        self._position_cache: dict[str, bool] = {}

    async def initialize(self, broker) -> None:
        """Initialize strategy."""
        await super().initialize(broker)
        self._logger.info(
            "RSIStrategy initialized: "
            "period=%s, oversold=%s, overbought=%s, order_qty=%s",
            self.period,
            self.oversold,
            self.overbought,
            self.order_qty,
        )

    def runtime_defaults(self) -> dict[str, Any]:
        """Preferred CLI defaults for this strategy."""
        return {
            "symbol": "AAPL",
            "mode": "replay",
            "days": 30,
            "speed": 10000.0,
            "timeframe": "1h",
        }

    def supports_multi_symbol(self) -> bool:
        """RSI implementation keeps per-symbol state, so it is multi-safe."""
        return True

    async def on_bar(self, bar: Bar) -> None:
        """Process bar and check RSI signal.

        Args:
            bar: Market data bar
        """
        state = self._get_symbol_state(bar.symbol)
        state["prices"].append(bar.close)

        # Keep compatibility state synchronized for users/tests that inspect these fields.
        self.prices = state["prices"]
        self.gains = state["gains"]
        self.losses = state["losses"]
        self.previous_rsi = state["previous_rsi"]

        self.bars_count += 1

        # Need enough data
        if len(state["prices"]) < 2:
            return

        # Calculate price change
        change = state["prices"][-1] - state["prices"][-2]
        if change > 0:
            gain = change
            loss = 0.0
        else:
            gain = 0.0
            loss = abs(change)

        state["gains"].append(gain)
        state["losses"].append(loss)

        # Bootstrap Wilder averages using the initial window.
        if state["avg_gain"] is None or state["avg_loss"] is None:
            if len(state["gains"]) < self.period:
                return

            state["avg_gain"] = sum(state["gains"]) / self.period
            state["avg_loss"] = sum(state["losses"]) / self.period
        else:
            # Wilder smoothing for subsequent bars.
            state["avg_gain"] = ((state["avg_gain"] * (self.period - 1)) + gain) / self.period
            state["avg_loss"] = ((state["avg_loss"] * (self.period - 1)) + loss) / self.period

        rsi = self._calculate_rsi(state["avg_gain"], state["avg_loss"])
        self._logger.debug("%s: Close=%.2f, RSI=%.2f", bar.symbol, bar.close, rsi)

        in_position = await self._has_position(bar.symbol)

        # Check for signals
        if (
            rsi < self.oversold
            and (state["previous_rsi"] is None or state["previous_rsi"] >= self.oversold)
            and not in_position
        ):
            self._logger.info("BUY signal: RSI=%.2f < %s (oversold)", rsi, self.oversold)
            await self.buy(bar.symbol, qty=self.order_qty, limit_price=bar.close)
            self._position_cache[bar.symbol] = True

        elif (
            rsi > self.overbought
            and (state["previous_rsi"] is None or state["previous_rsi"] <= self.overbought)
            and in_position
        ):
            self._logger.info("SELL signal: RSI=%.2f > %s (overbought)", rsi, self.overbought)
            await self.sell(bar.symbol, qty=self.order_qty, limit_price=bar.close)
            self._position_cache[bar.symbol] = False

        state["previous_rsi"] = rsi
        self.previous_rsi = rsi

    def _calculate_rsi(
        self,
        avg_gain: Optional[float] = None,
        avg_loss: Optional[float] = None,
    ) -> float:
        """Calculate RSI.

        Returns:
            RSI value (0-100)
        """
        if avg_gain is None:
            avg_gain = sum(self.gains) / len(self.gains) if self.gains else 0.0
        if avg_loss is None:
            avg_loss = sum(self.losses) / len(self.losses) if self.losses else 0.0

        if avg_gain == 0 and avg_loss == 0:
            return 50.0

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 0.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _get_symbol_state(self, symbol: str) -> dict:
        """Get or create RSI state for a symbol."""
        if symbol not in self._symbol_state:
            self._symbol_state[symbol] = {
                "prices": deque(maxlen=self.period + 1),
                "gains": deque(maxlen=self.period),
                "losses": deque(maxlen=self.period),
                "avg_gain": None,
                "avg_loss": None,
                "previous_rsi": None,
            }
        return self._symbol_state[symbol]

    async def _has_position(self, symbol: str) -> bool:
        """Return True when broker has a long position for the symbol."""
        if not self.broker:
            return self._position_cache.get(symbol, False)

        try:
            position = await self.broker.get_position(symbol)
            has_position = bool(position and position.qty > 0)
            self._position_cache[symbol] = has_position
            return has_position
        except (BrokerError, AttributeError, TypeError) as exc:
            self._logger.warning("Position check failed for %s: %s", symbol, exc)
            return self._position_cache.get(symbol, False)

    async def finalize(self) -> None:
        """Clean up strategy."""
        await super().finalize()
        self._logger.info("RSIStrategy finalized after %s bars", self.bars_count)
