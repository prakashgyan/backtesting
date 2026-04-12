"""Bollinger Bands strategy example."""

import math
from collections import deque
from typing import Any, Optional, Tuple

from day_trader.models import Bar
from day_trader.strategy.base import Strategy


class BollingerBandsStrategy(Strategy):
    """Bollinger Bands Strategy.

    Signals:
    - BUY when price touches lower band (support)
    - SELL when price touches upper band (resistance)

    Bollinger Bands = SMA ± (std_dev * num_std_dev)
    """

    def __init__(self, period: int = 20, num_std_dev: float = 2.0):
        """Initialize Bollinger Bands strategy.

        Args:
            period: SMA period (default: 20)
            num_std_dev: Number of standard deviations (default: 2)
        """
        super().__init__()
        self.period = period
        self.num_std_dev = num_std_dev

        # Price history
        self.prices: deque = deque(maxlen=period)
        self.bars_count = 0
        self.previous_position: Optional[str] = None

    async def initialize(self, broker) -> None:
        """Initialize strategy."""
        await super().initialize(broker)
        self._logger.info(
            f"BollingerBandsStrategy initialized: period={self.period}, "
            f"std_dev={self.num_std_dev}"
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
        """Process bar and check Bollinger Bands signal.

        Args:
            bar: Market data bar
        """
        self.prices.append(bar.close)
        self.bars_count += 1

        # Need enough data
        if len(self.prices) < self.period:
            return

        # Calculate bands
        middle_band, upper_band, lower_band = self._calculate_bands()

        self._logger.debug(
            f"{bar.symbol}: Close={bar.close:.2f}, "
            f"Upper={upper_band:.2f}, Middle={middle_band:.2f}, Lower={lower_band:.2f}"
        )

        # Check for signals
        if bar.close <= lower_band and self.previous_position != "LONG":
            self._logger.info(
                f"BUY signal: Price={bar.close:.2f} <= Lower Band={lower_band:.2f} (support)"
            )
            await self.buy(bar.symbol, qty=10, limit_price=bar.close)
            self.previous_position = "LONG"

        elif bar.close >= upper_band and self.previous_position == "LONG":
            self._logger.info(
                f"SELL signal: Price={bar.close:.2f} >= Upper Band={upper_band:.2f} (resistance)"
            )
            await self.sell(bar.symbol, qty=10, limit_price=bar.close)
            self.previous_position = None

    def _calculate_bands(self) -> Tuple[float, float, float]:
        """Calculate Bollinger Bands.

        Returns:
            Tuple of (middle_band, upper_band, lower_band)
        """
        if len(self.prices) < self.period:
            return 0.0, 0.0, 0.0

        # Calculate SMA
        prices_list = list(self.prices)
        middle_band = sum(prices_list) / len(prices_list)

        # Calculate standard deviation
        variance = sum((p - middle_band) ** 2 for p in prices_list) / len(prices_list)
        std_dev = math.sqrt(variance)

        # Calculate bands
        upper_band = middle_band + (self.num_std_dev * std_dev)
        lower_band = middle_band - (self.num_std_dev * std_dev)

        return middle_band, upper_band, lower_band

    async def finalize(self) -> None:
        """Clean up strategy."""
        await super().finalize()
        self._logger.info(f"BollingerBandsStrategy finalized after {self.bars_count} bars")
