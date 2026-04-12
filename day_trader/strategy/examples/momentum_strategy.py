"""Momentum strategy example."""

from collections import deque
from typing import Any

from day_trader.models import Bar
from day_trader.strategy.base import Strategy


class MomentumStrategy(Strategy):
    """Momentum Strategy based on price rate of change.

    Signals:
    - BUY when momentum (price change) exceeds threshold
    - SELL when momentum goes negative

    Momentum = (Current Close - Close N periods ago) / Close N periods ago * 100
    """

    def __init__(self, period: int = 10, momentum_threshold: float = 1.0):
        """Initialize Momentum strategy.

        Args:
            period: Number of periods for momentum calculation
            momentum_threshold: Minimum momentum threshold to trigger signals
        """
        super().__init__()
        self.period = period
        self.momentum_threshold = momentum_threshold

        # Price history
        self.prices: deque = deque(maxlen=period + 1)
        self.bars_count = 0
        self.in_position = False

    async def initialize(self, broker) -> None:
        """Initialize strategy."""
        await super().initialize(broker)
        self._logger.info(
            f"MomentumStrategy initialized: period={self.period}, "
            f"threshold={self.momentum_threshold}%"
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
        """Process bar and check momentum signal.

        Args:
            bar: Market data bar
        """
        self.prices.append(bar.close)
        self.bars_count += 1

        # Need enough data
        if len(self.prices) <= self.period:
            return

        # Calculate momentum
        momentum = self._calculate_momentum()
        self._logger.debug(f"{bar.symbol}: Close={bar.close:.2f}, Momentum={momentum:.2f}%")

        # Check for buy signal
        if (
            momentum > self.momentum_threshold
            and not self.in_position
        ):
            self._logger.info(
                f"BUY signal: Momentum={momentum:.2f}% > "
                f"{self.momentum_threshold}% (uptrend detected)"
            )
            await self.buy(bar.symbol, qty=15, limit_price=bar.close)
            self.in_position = True

        # Check for sell signal
        elif momentum < 0 and self.in_position:
            self._logger.info(
                f"SELL signal: Momentum={momentum:.2f}% < 0% (downtrend detected)"
            )
            await self.sell(bar.symbol, qty=15, limit_price=bar.close)
            self.in_position = False

    def _calculate_momentum(self) -> float:
        """Calculate momentum percentage.

        Returns:
            Momentum as percentage
        """
        if len(self.prices) < self.period + 1:
            return 0.0

        current = self.prices[-1]
        previous = self.prices[0]

        if previous == 0:
            return 0.0

        momentum = ((current - previous) / previous) * 100
        return momentum

    async def finalize(self) -> None:
        """Clean up strategy."""
        await super().finalize()
        self._logger.info(f"MomentumStrategy finalized after {self.bars_count} bars")
