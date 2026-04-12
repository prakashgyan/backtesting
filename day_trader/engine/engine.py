"""Engine orchestrator for trading system.

Coordinates data flow: DataStream → Strategy → Broker
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from day_trader.core.base import (
    BrokerInterface,
    DataStreamInterface,
    StrategyInterface,
)
from day_trader.core.exceptions import EngineError, StrategyError, BrokerError
from day_trader.logging import get_logger
from day_trader.metrics import MetricsCalculator
from day_trader.models import Bar, Order
from day_trader.run_tracking import EventStoreInterface, RunTracker

logger = get_logger(__name__)


class RunSession:
    """Manages the run-tracking lifecycle for a single engine execution.

    Owns the EventStore, the run_id, and the terminal status so Engine does
    not have to juggle these details directly.
    """

    def __init__(self) -> None:
        self._store: Optional[EventStoreInterface] = None
        self._run_status = "COMPLETED"
        self._fatal_error_message: Optional[str] = None

    @property
    def store(self) -> Optional[EventStoreInterface]:
        return self._store

    @property
    def run_status(self) -> str:
        return self._run_status

    @property
    def fatal_error_message(self) -> Optional[str]:
        return self._fatal_error_message

    def mark_failed(self, message: str) -> None:
        self._run_status = "FAILED"
        self._fatal_error_message = message

    def start(
        self,
        db_path: Path,
        strategy: StrategyInterface,
        broker: BrokerInterface,
        data_stream: DataStreamInterface,
        initial_capital: float,
        metadata: dict[str, Any],
    ) -> None:
        """Initialise the SQLite event store and attach it to the strategy."""
        try:
            store = RunTracker(db_path)
            run_id = store.start_run(
                strategy_name=strategy.__class__.__name__,
                broker_name=broker.__class__.__name__,
                data_stream_name=data_stream.__class__.__name__,
                initial_capital=initial_capital,
                metadata=metadata,
            )
            strategy.attach_run_tracker(store, run_id)
            self._store = store
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            logger.warning("Run tracker initialisation failed: %s", exc)
            self._store = None

    def complete(
        self,
        bars_processed: int,
        trades_executed: int,
        errors: int,
        elapsed_seconds: float,
    ) -> None:
        """Finalise the run record and close the store."""
        if not self._store:
            return
        if self._run_status != "FAILED" and errors > 0:
            self._run_status = "COMPLETED_WITH_ERRORS"
        self._store.complete_run(
            status=self._run_status,
            bars_processed=bars_processed,
            trades_executed=trades_executed,
            errors=errors,
            elapsed_seconds=elapsed_seconds,
            error_message=self._fatal_error_message,
        )
        self._store.close()


class Engine:
    """Main orchestrator for trading engine.

    Manages the event loop connecting data stream to strategy to broker.

    Attributes:
        data_stream: Source of market data
        strategy: Trading strategy to execute
        broker: Broker for order execution
        metrics: Performance metrics calculator
    """

    def __init__(
        self,
        data_stream: DataStreamInterface,
        strategy: StrategyInterface,
        broker: BrokerInterface,
        initial_capital: float = 10000.0,
        run_metrics_csv_path: Optional[Path] = None,
        run_events_db_path: Optional[Path] = None,
        run_metadata: Optional[dict[str, Any]] = None,
        max_consecutive_errors: int = 10,
    ) -> None:
        """Initialize engine with components.

        Args:
            data_stream: DataStream implementation (live or replay)
            strategy: Strategy implementation
            broker: Broker implementation
            initial_capital: Starting account capital for metrics
            run_metrics_csv_path: Optional path to append run metrics CSV
            run_events_db_path: Optional path for SQLite run/event tracking
            run_metadata: Optional run metadata columns for CSV logging
        """
        self.data_stream = data_stream
        self.strategy = strategy
        self.broker = broker
        self.metrics = MetricsCalculator(initial_capital=initial_capital)
        self.run_metrics_csv_path = run_metrics_csv_path
        self.run_events_db_path = run_events_db_path
        self.run_metadata = run_metadata or {}
        self._max_consecutive_errors = max_consecutive_errors

        # State tracking
        self._running = False
        self._bars_processed = 0
        self._trades_executed = 0
        self._start_time: Optional[datetime] = None
        self._errors: list[Exception] = []
        self._consecutive_errors = 0
        self._run_session = RunSession()

    async def run(self) -> None:
        """Run the trading engine.

        Main event loop:
        1. Connect broker
        2. Connect data stream
        3. Initialize strategy
        4. Emit bars and execute strategy
        5. Finalize strategy
        6. Cleanup and display metrics

        Raises:
            EngineError: If engine fails to initialize or run
        """
        self._running = True
        self._start_time = datetime.now(timezone.utc)

        if self.run_events_db_path:
            self._run_session.start(
                db_path=self.run_events_db_path,
                strategy=self.strategy,
                broker=self.broker,
                data_stream=self.data_stream,
                initial_capital=self.metrics.initial_capital,
                metadata=self.run_metadata,
            )

        try:
            logger.info("Starting trading engine")

            # Connect broker
            try:
                await self.broker.connect()
                logger.debug("Broker connected")
            except BrokerError as e:
                raise EngineError(f"Failed to connect broker: {e}")

            # Connect data stream
            try:
                await self.data_stream.connect()
                logger.debug("Data stream connected")
            except Exception as e:
                await self.broker.disconnect()
                raise EngineError(f"Failed to connect data stream: {e}")

            # Initialize strategy
            try:
                await self.strategy.initialize(self.broker)
                logger.debug("Strategy initialized")
            except StrategyError as e:
                await self._cleanup()
                raise EngineError(f"Strategy initialization failed: {e}")

            # Subscribe to bars
            await self.data_stream.subscribe(self._on_bar)

            # Start data stream (blocking)
            logger.info("Engine running - waiting for market data")
            await self.data_stream.start()

        except EngineError as e:
            self._run_session.mark_failed(str(e))
            logger.error(f"Engine error: {e}")
            raise
        except Exception as e:
            self._run_session.mark_failed(str(e))
            logger.error(f"Unexpected engine error: {e}")
            raise EngineError(f"Unexpected error: {e}")
        finally:
            await self._cleanup()

    async def _on_bar(self, bar: Bar) -> None:
        """Process incoming bar.

        Called by data stream for each bar.

        Args:
            bar: Market data bar
        """
        self._bars_processed += 1

        # Set bar timestamp for event logging (simulated time in replay mode)
        if hasattr(self.strategy, 'set_current_bar_time'):
            self.strategy.set_current_bar_time(bar.timestamp)

        try:
            logger.debug(f"Processing bar: {bar.symbol} @ {bar.close}")
            await self.strategy.on_bar(bar)
            self._consecutive_errors = 0
        except (StrategyError, Exception) as e:
            logger.error(f"Error processing bar: {e}")
            self._errors.append(e)
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                logger.error(
                    f"Aborting: {self._consecutive_errors} consecutive bar errors "
                    f"(threshold={self._max_consecutive_errors})"
                )
                await self.data_stream.stop()

    async def _cleanup(self) -> None:
        """Clean up engine resources and display metrics."""
        try:
            logger.info("Cleaning up engine resources")

            # Finalize strategy
            if hasattr(self, "strategy"):
                try:
                    await self.strategy.finalize()
                except Exception as e:
                    logger.error(f"Strategy finalization error: {e}")

            # Stop data stream
            if hasattr(self, "data_stream"):
                try:
                    await self.data_stream.stop()
                    await self.data_stream.disconnect()
                except Exception as e:
                    logger.error(f"Data stream disconnect error: {e}")

            # Disconnect broker
            if hasattr(self, "broker"):
                try:
                    await self.broker.disconnect()
                except Exception as e:
                    logger.error(f"Broker disconnect error: {e}")

            self._running = False
            self._trades_executed = self.metrics.hydrate_from_orders(
                self.strategy.executed_orders
            )
            elapsed = (datetime.now(timezone.utc) - self._start_time).total_seconds() if self._start_time else 0
            run_stats = {
                "bars_processed": self._bars_processed,
                "trades_executed": self._trades_executed,
                "errors": len(self._errors),
                "elapsed_seconds": elapsed,
            }
            logger.info(
                f"Engine stopped. Bars: {self._bars_processed}, "
                f"Trades: {self._trades_executed}, "
                f"Duration: {elapsed:.2f}s, "
                f"Errors: {len(self._errors)}"
            )

            metrics = self.metrics.calculate_metrics()
            logger.info("\n" + "=" * 60)
            logger.info("TRADING METRICS")
            logger.info("=" * 60)
            logger.info(f"Total Trades:      {metrics.total_trades}")
            logger.info(f"Winning Trades:    {metrics.winning_trades}")
            logger.info(f"Losing Trades:     {metrics.losing_trades}")
            logger.info(f"Win Rate:          {metrics.win_rate:.2f}%")
            logger.info(f"Profit Factor:     {metrics.profit_factor:.2f}")
            logger.info(f"Gross Profit:      ${metrics.gross_profit:,.2f}")
            logger.info(f"Gross Loss:        ${metrics.gross_loss:,.2f}")
            logger.info(f"Realized P&L:      ${metrics.realized_pnl:,.2f}")
            logger.info(f"Unrealized P&L:    ${metrics.unrealized_pnl:,.2f}")
            logger.info(f"Total P&L:         ${metrics.total_pnl:,.2f}")
            logger.info(f"Returns:           {metrics.returns_pct:.2f}%")
            logger.info(f"Max Drawdown:      {metrics.max_drawdown:.2f}%")
            logger.info(f"Sharpe Ratio:      {metrics.sharpe_ratio:.2f}")
            logger.info("=" * 60)

            if self.run_metrics_csv_path:
                csv_metadata = {
                    "strategy": self.strategy.__class__.__name__,
                    "broker": self.broker.__class__.__name__,
                    "data_stream": self.data_stream.__class__.__name__,
                }
                csv_metadata.update(self.run_metadata)
                self.metrics.append_run_metrics_to_csv(
                    csv_path=self.run_metrics_csv_path,
                    engine_stats=run_stats,
                    run_metadata=csv_metadata,
                    metrics=metrics,
                )

            self._run_session.complete(
                bars_processed=self._bars_processed,
                trades_executed=self._trades_executed,
                errors=len(self._errors),
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    @property
    def running(self) -> bool:
        """Check if engine is running."""
        return self._running

    @property
    def stats(self) -> dict:
        """Get engine statistics."""
        elapsed = (
            (datetime.now(timezone.utc) - self._start_time).total_seconds()
            if self._start_time
            else 0
        )
        return {
            "bars_processed": self._bars_processed,
            "trades_executed": self._trades_executed,
            "errors": len(self._errors),
            "elapsed_seconds": elapsed,
        }

    async def stop(self) -> None:
        """Stop the engine gracefully."""
        logger.info("Stopping engine")
        await self.data_stream.stop()

