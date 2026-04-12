"""Simple SMA crossover strategy example."""

from collections import deque
from typing import Any, Optional

from day_trader.models import Bar
from day_trader.strategy.base import Strategy


class SimpleSMAStrategy(Strategy):
    """Simple Moving Average Crossover Strategy.

    Signals:
    - BUY when 5-bar SMA crosses above 20-bar SMA
    - SELL when 5-bar SMA crosses below 20-bar SMA

    This is a simple example strategy for demonstration purposes.
    """

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
    ) -> None:
        """Initialize SMA strategy.

        Args:
            short_window: Window size for short-term SMA
            long_window: Window size for long-term SMA
        """
        super().__init__()
        self.short_window = short_window
        self.long_window = long_window

        # Price history buffer
        self.prices: deque = deque(maxlen=long_window)
        self.bars_count = 0
        self.previous_position: Optional[str] = None

    async def initialize(self, broker) -> None:
        """Initialize strategy."""
        await super().initialize(broker)
        self._logger.info(
            f"SimpleSMAStrategy initialized: short={self.short_window}, "
            f"long={self.long_window}"
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

    async def on_bar(self, bar: Bar) -> None:
        """Process bar and check for crossover signals.

        Args:
            bar: Market data bar
        """
        # Add close price to history
        self.prices.append(bar.close)
        self.bars_count += 1

        # Need enough data to calculate SMAs
        if len(self.prices) < self.long_window:
            self._logger.debug(
                f"Accumulating data: {len(self.prices)}/{self.long_window}"
            )
            return

        # Calculate SMAs
        short_sma = self._calculate_sma(self.short_window)
        long_sma = self._calculate_sma(self.long_window)

        self._logger.debug(
            f"{bar.symbol}: Close={bar.close:.2f}, "
            f"SMA5={short_sma:.2f}, SMA20={long_sma:.2f}"
        )

        # Check for signals
        if short_sma > long_sma and self.previous_position != "LONG":
            self._logger.info(f"BUY signal: SMA5={short_sma:.2f} > SMA20={long_sma:.2f}")
            await self.buy(bar.symbol, qty=10, limit_price=bar.close)
            self.previous_position = "LONG"

        elif short_sma < long_sma and self.previous_position == "LONG":
            self._logger.info(
                f"SELL signal: SMA5={short_sma:.2f} < SMA20={long_sma:.2f}"
            )
            await self.sell(bar.symbol, qty=10, limit_price=bar.close)
            self.previous_position = None

    def _calculate_sma(self, period: int) -> float:
        """Calculate simple moving average.

        Args:
            period: Number of bars to average

        Returns:
            Simple moving average
        """
        if len(self.prices) < period:
            return 0.0

        recent_prices = list(self.prices)[-period:]
        return sum(recent_prices) / len(recent_prices)

    async def finalize(self) -> None:
        """Clean up strategy."""
        await super().finalize()
        self._logger.info(f"SimpleSMAStrategy finalized after {self.bars_count} bars")
