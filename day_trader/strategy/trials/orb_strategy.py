"""Opening Range Breakout (ORB) strategy.

Designed for intraday minute bars. Uses the first N minutes after market open
to define an opening range, then looks for breakouts with volume confirmation.
"""

from collections import deque
from datetime import date, datetime, time
from math import floor
from statistics import mean
from typing import Any, Deque, Literal, Optional
from zoneinfo import ZoneInfo

from day_trader.models import Bar
from day_trader.strategy.base import Strategy


class OpeningRangeBreakoutStrategy(Strategy):
    """Opening Range Breakout strategy with risk-based sizing.

    Notes:
    - Best used with 1-minute or 5-minute bars.
    - Default mode is "retest" for safer entries.
    - Short entries are disabled by default to remain compatible with
      the simulated broker's long-only behavior.
    """

    def __init__(
        self,
        opening_range_minutes: int = 15,
        entry_mode: Literal["aggressive", "retest"] = "retest",
        max_retest_bars: int = 3,
        volume_lookback: int = 20,
        volume_spike_multiplier: float = 1.8,
        require_volume_spike: bool = True,
        risk_per_trade_pct: float = 0.01,
        reward_to_risk: float = 2.0,
        use_vwap_filter: bool = False,
        allow_short: bool = False,
        position_risk_floor: float = 0.01,
        regular_session_start: time = time(9, 30),
        regular_session_end: time = time(16, 0),
        force_flat_time: time = time(15, 55),
    ) -> None:
        super().__init__()

        if opening_range_minutes <= 0:
            raise ValueError("opening_range_minutes must be positive")
        if entry_mode not in ("aggressive", "retest"):
            raise ValueError("entry_mode must be 'aggressive' or 'retest'")
        if max_retest_bars <= 0:
            raise ValueError("max_retest_bars must be positive")
        if volume_lookback <= 1:
            raise ValueError("volume_lookback must be > 1")
        if volume_spike_multiplier <= 0:
            raise ValueError("volume_spike_multiplier must be positive")
        if not 0 < risk_per_trade_pct <= 0.05:
            raise ValueError("risk_per_trade_pct should be between 0 and 0.05")
        if reward_to_risk <= 0:
            raise ValueError("reward_to_risk must be positive")

        self.opening_range_minutes = opening_range_minutes
        self.entry_mode = entry_mode
        self.max_retest_bars = max_retest_bars
        self.volume_lookback = volume_lookback
        self.volume_spike_multiplier = volume_spike_multiplier
        self.require_volume_spike = require_volume_spike
        self.risk_per_trade_pct = risk_per_trade_pct
        self.reward_to_risk = reward_to_risk
        self.use_vwap_filter = use_vwap_filter
        self.allow_short = allow_short
        self.position_risk_floor = position_risk_floor

        self.regular_session_start = regular_session_start
        self.regular_session_end = regular_session_end
        self.force_flat_time = force_flat_time

        self._et_tz = ZoneInfo("America/New_York")

        self._bars_count = 0
        self._current_day: Optional[date] = None
        self._traded_today = False
        self._warned_missing_opening_range = False

        self._or_high: Optional[float] = None
        self._or_low: Optional[float] = None
        self._premarket_high: Optional[float] = None
        self._premarket_low: Optional[float] = None

        self._volume_history: Deque[float] = deque(maxlen=volume_lookback)

        self._vwap_pv_sum = 0.0
        self._vwap_volume_sum = 0.0

        self._pending_side: Optional[str] = None
        self._pending_level: Optional[float] = None
        self._pending_bars_left = 0

        self._in_position = False
        self._position_side: Optional[str] = None
        self._position_qty = 0
        self._entry_price = 0.0
        self._stop_price = 0.0
        self._target_price = 0.0
        self._one_r_price = 0.0
        self._partial_taken = False

    async def initialize(self, broker) -> None:
        await super().initialize(broker)
        self._logger.info(
            "ORB initialized: window=%sm, entry_mode=%s, rr=%.2f, volume_spike=%.2fx",
            self.opening_range_minutes,
            self.entry_mode,
            self.reward_to_risk,
            self.volume_spike_multiplier,
        )

    def runtime_defaults(self) -> dict[str, Any]:
        """Preferred CLI defaults for this strategy."""
        return {
            "symbol": "AAPL",
            "mode": "replay",
            "days": 90,
            "speed": 10000.0,
            "timeframe": "1min",
        }

    async def on_bar(self, bar: Bar) -> None:
        self._bars_count += 1

        bar_dt = self._to_eastern(bar.timestamp)
        bar_day = bar_dt.date()
        bar_time = bar_dt.time()

        if self._current_day != bar_day:
            self._reset_day_state(bar_day)

        if bar_time < self.regular_session_start:
            self._premarket_high = bar.high if self._premarket_high is None else max(self._premarket_high, bar.high)
            self._premarket_low = bar.low if self._premarket_low is None else min(self._premarket_low, bar.low)
            return

        if bar_time >= self.regular_session_end:
            return

        self._volume_history.append(bar.volume)
        self._update_vwap(bar)

        if self._is_opening_range_time(bar_time):
            self._or_high = bar.high if self._or_high is None else max(self._or_high, bar.high)
            self._or_low = bar.low if self._or_low is None else min(self._or_low, bar.low)
            return

        if self._or_high is None or self._or_low is None:
            if not self._warned_missing_opening_range:
                self._warned_missing_opening_range = True
                self._logger.warning(
                    "No opening range established. Strategy expects intraday minute bars."
                )
            return

        if self._in_position:
            await self._manage_open_position(bar, bar_time)
            return

        if self._traded_today:
            return

        avg_volume = self._average_volume()
        if self.entry_mode == "aggressive":
            await self._try_aggressive_entry(bar, avg_volume)
            return

        await self._try_retest_entry(bar, avg_volume)

    async def finalize(self) -> None:
        await super().finalize()
        self._logger.info("ORB finalized after %s bars", self._bars_count)

    async def _try_aggressive_entry(self, bar: Bar, avg_volume: Optional[float]) -> None:
        if self._is_long_breakout(bar, avg_volume):
            await self._enter_position("LONG", bar)
            return

        if self.allow_short and self._is_short_breakout(bar, avg_volume):
            await self._enter_position("SHORT", bar)

    async def _try_retest_entry(self, bar: Bar, avg_volume: Optional[float]) -> None:
        if self._pending_side is None:
            if self._is_long_breakout(bar, avg_volume):
                self._set_pending("LONG", self._or_high)
                return
            if self.allow_short and self._is_short_breakout(bar, avg_volume):
                self._set_pending("SHORT", self._or_low)
                return
            return

        self._pending_bars_left -= 1
        if self._pending_bars_left < 0:
            self._clear_pending()
            return

        assert self._pending_level is not None
        if self._pending_side == "LONG":
            retest_holds = bar.low <= self._pending_level and bar.close > self._pending_level
            if retest_holds:
                await self._enter_position("LONG", bar)
                self._clear_pending()
                return

        if self._pending_side == "SHORT":
            retest_holds = bar.high >= self._pending_level and bar.close < self._pending_level
            if retest_holds:
                await self._enter_position("SHORT", bar)
                self._clear_pending()
                return

    async def _enter_position(self, side: str, bar: Bar) -> None:
        stop = self._or_low if side == "LONG" else self._or_high
        if stop is None:
            return

        entry = bar.close
        risk_per_share = abs(entry - stop)
        if risk_per_share < self.position_risk_floor:
            self._logger.info(
                "Skip %s entry: risk/share %.4f below floor %.4f",
                side,
                risk_per_share,
                self.position_risk_floor,
            )
            return

        qty = await self._calculate_position_size(entry=entry, stop=stop, side=side)
        if qty <= 0:
            self._logger.info("Skip %s entry: calculated quantity is 0", side)
            return

        if side == "LONG":
            await self.buy(
                bar.symbol,
                qty=qty,
                limit_price=entry,
                reason="ORB long breakout entry",
                details={"entry_mode": self.entry_mode, "or_high": self._or_high, "or_low": self._or_low},
            )
            target = entry + (risk_per_share * self.reward_to_risk)
            one_r = entry + risk_per_share
        else:
            await self.sell(
                bar.symbol,
                qty=qty,
                limit_price=entry,
                reason="ORB short breakout entry",
                details={"entry_mode": self.entry_mode, "or_high": self._or_high, "or_low": self._or_low},
            )
            target = entry - (risk_per_share * self.reward_to_risk)
            one_r = entry - risk_per_share

        self._in_position = True
        self._position_side = side
        self._position_qty = qty
        self._entry_price = entry
        self._stop_price = stop
        self._target_price = target
        self._one_r_price = one_r
        self._partial_taken = False
        self._traded_today = True

        self._logger.info(
            "%s entry: price=%.2f, qty=%s, stop=%.2f, target=%.2f",
            side,
            entry,
            qty,
            stop,
            target,
        )

    async def _manage_open_position(self, bar: Bar, bar_time: time) -> None:
        if self._position_side is None or self._position_qty <= 0:
            return

        if not self._partial_taken:
            await self._try_take_partial(bar)

        if self._position_side == "LONG" and bar.low <= self._stop_price:
            await self._exit_position(bar.symbol, self._stop_price, "Stop loss hit")
            return

        if self._position_side == "SHORT" and bar.high >= self._stop_price:
            await self._exit_position(bar.symbol, self._stop_price, "Stop loss hit")
            return

        if self._position_side == "LONG" and bar.high >= self._target_price:
            await self._exit_position(bar.symbol, self._target_price, "Target hit")
            return

        if self._position_side == "SHORT" and bar.low <= self._target_price:
            await self._exit_position(bar.symbol, self._target_price, "Target hit")
            return

        if bar_time >= self.force_flat_time:
            await self._exit_position(bar.symbol, bar.close, "End-of-day flatten")

    async def _try_take_partial(self, bar: Bar) -> None:
        if self._position_qty <= 1:
            return

        if self._position_side == "LONG" and bar.high >= self._one_r_price:
            qty_to_close = max(1, self._position_qty // 2)
            await self.sell(
                bar.symbol,
                qty=qty_to_close,
                limit_price=self._one_r_price,
                reason="ORB partial take-profit at 1R",
            )
            self._position_qty -= qty_to_close
            self._stop_price = self._entry_price
            self._partial_taken = True
            self._logger.info(
                "Partial at 1R: sold %s, remaining=%s, stop moved to breakeven",
                qty_to_close,
                self._position_qty,
            )
            return

        if self._position_side == "SHORT" and bar.low <= self._one_r_price:
            qty_to_close = max(1, self._position_qty // 2)
            await self.buy(
                bar.symbol,
                qty=qty_to_close,
                limit_price=self._one_r_price,
                reason="ORB partial cover at 1R",
            )
            self._position_qty -= qty_to_close
            self._stop_price = self._entry_price
            self._partial_taken = True
            self._logger.info(
                "Partial at 1R: covered %s, remaining=%s, stop moved to breakeven",
                qty_to_close,
                self._position_qty,
            )

    async def _exit_position(self, symbol: str, exit_price: float, reason: str) -> None:
        if self._position_qty <= 0 or self._position_side is None:
            return

        qty = self._position_qty
        if self._position_side == "LONG":
            await self.sell(symbol, qty=qty, limit_price=exit_price, reason=reason)
        else:
            await self.buy(symbol, qty=qty, limit_price=exit_price, reason=reason)

        self._logger.info(
            "Exit %s: price=%.2f, qty=%s, reason=%s",
            self._position_side,
            exit_price,
            qty,
            reason,
        )

        self._in_position = False
        self._position_side = None
        self._position_qty = 0
        self._entry_price = 0.0
        self._stop_price = 0.0
        self._target_price = 0.0
        self._one_r_price = 0.0
        self._partial_taken = False

    async def _calculate_position_size(self, entry: float, stop: float, side: str) -> int:
        assert self.broker is not None
        account = await self.broker.get_account()

        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            return 0

        risk_budget = account.equity * self.risk_per_trade_pct
        raw_qty = floor(risk_budget / risk_per_share)
        if raw_qty <= 0:
            return 0

        if side == "LONG" and entry > 0:
            max_affordable = floor(account.buying_power / entry)
            return max(0, min(raw_qty, max_affordable))

        return max(0, raw_qty)

    def _is_long_breakout(self, bar: Bar, avg_volume: Optional[float]) -> bool:
        if self._or_high is None:
            return False
        close_breaks = bar.close > self._or_high
        volume_ok = self._volume_spike_ok(bar.volume, avg_volume)
        vwap_ok = True if not self.use_vwap_filter else bar.close >= self._vwap_price()
        return close_breaks and volume_ok and vwap_ok

    def _is_short_breakout(self, bar: Bar, avg_volume: Optional[float]) -> bool:
        if self._or_low is None:
            return False
        close_breaks = bar.close < self._or_low
        volume_ok = self._volume_spike_ok(bar.volume, avg_volume)
        vwap_ok = True if not self.use_vwap_filter else bar.close <= self._vwap_price()
        return close_breaks and volume_ok and vwap_ok

    def _volume_spike_ok(self, current_volume: float, avg_volume: Optional[float]) -> bool:
        if not self.require_volume_spike:
            return True
        if avg_volume is None or avg_volume <= 0:
            return False
        return current_volume >= (avg_volume * self.volume_spike_multiplier)

    def _average_volume(self) -> Optional[float]:
        if len(self._volume_history) < self.volume_lookback:
            return None
        return mean(self._volume_history)

    def _update_vwap(self, bar: Bar) -> None:
        typical_price = (bar.high + bar.low + bar.close) / 3.0
        self._vwap_pv_sum += typical_price * bar.volume
        self._vwap_volume_sum += bar.volume

    def _vwap_price(self) -> float:
        if self._vwap_volume_sum <= 0:
            return 0.0
        return self._vwap_pv_sum / self._vwap_volume_sum

    def _is_opening_range_time(self, bar_time: time) -> bool:
        minute_of_day = (bar_time.hour * 60) + bar_time.minute
        start_minute = (self.regular_session_start.hour * 60) + self.regular_session_start.minute
        end_minute = start_minute + self.opening_range_minutes
        return start_minute <= minute_of_day < end_minute

    def _set_pending(self, side: str, level: Optional[float]) -> None:
        if level is None:
            return
        self._pending_side = side
        self._pending_level = level
        self._pending_bars_left = self.max_retest_bars

    def _clear_pending(self) -> None:
        self._pending_side = None
        self._pending_level = None
        self._pending_bars_left = 0

    def _reset_day_state(self, trading_day: date) -> None:
        self._current_day = trading_day
        self._traded_today = False
        self._warned_missing_opening_range = False

        self._or_high = None
        self._or_low = None
        self._premarket_high = None
        self._premarket_low = None
        self._volume_history.clear()

        self._vwap_pv_sum = 0.0
        self._vwap_volume_sum = 0.0

        self._clear_pending()

    def _to_eastern(self, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=self._et_tz)
        return timestamp.astimezone(self._et_tz)
