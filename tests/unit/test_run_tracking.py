"""Unit tests for SQLite run tracking."""

import sqlite3

import pytest

from day_trader.run_tracking import RunTracker
from day_trader.strategy.base import Strategy
from day_trader.models import Bar
from tests.unit.test_engine import MockBroker


class DummyStrategy(Strategy):
    """Minimal strategy for run tracking tests."""

    async def on_bar(self, bar: Bar) -> None:
        return None


class TestRunTracker:
    """Test cases for run and event persistence."""

    def test_run_lifecycle_persists(self, tmp_path) -> None:
        db_path = tmp_path / "run_history.db"
        tracker = RunTracker(db_path)

        run_id = tracker.start_run(
            strategy_name="DummyStrategy",
            broker_name="MockBroker",
            data_stream_name="MockDataStream",
            initial_capital=100000.0,
            metadata={"symbol": "AAPL", "mode": "replay", "timeframe": "1min"},
        )

        tracker.complete_run(
            status="COMPLETED",
            bars_processed=25,
            trades_executed=3,
            errors=0,
            elapsed_seconds=12.5,
        )
        tracker.close()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT run_id, status, bars_processed, trades_executed FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == run_id
        assert row[1] == "COMPLETED"
        assert row[2] == 25
        assert row[3] == 3

        events = conn.execute(
            "SELECT event_type FROM run_events WHERE run_id = ? ORDER BY event_id",
            (run_id,),
        ).fetchall()
        conn.close()

        assert [event[0] for event in events] == ["RUN_STARTED", "RUN_COMPLETED"]

    @pytest.mark.asyncio
    async def test_strategy_order_reason_is_persisted(self, tmp_path) -> None:
        db_path = tmp_path / "run_history.db"
        tracker = RunTracker(db_path)
        run_id = tracker.start_run(
            strategy_name="DummyStrategy",
            broker_name="MockBroker",
            data_stream_name="MockDataStream",
            initial_capital=100000.0,
            metadata={"symbol": "AAPL", "mode": "replay"},
        )

        strategy = DummyStrategy()
        broker = MockBroker()
        await broker.connect()
        await strategy.initialize(broker)
        strategy.attach_run_tracker(tracker, run_id)

        await strategy.buy(
            "AAPL",
            qty=10,
            limit_price=150.0,
            reason="Breakout above opening range",
            details={"entry_mode": "retest"},
        )

        tracker.complete_run(
            status="COMPLETED",
            bars_processed=1,
            trades_executed=1,
            errors=0,
            elapsed_seconds=0.1,
        )
        tracker.close()
        await broker.disconnect()

        conn = sqlite3.connect(db_path)
        events = conn.execute(
            """
            SELECT event_type, side, reason, status
            FROM run_events
            WHERE run_id = ?
            ORDER BY event_id
            """,
            (run_id,),
        ).fetchall()
        conn.close()

        assert any(e[0] == "ORDER_REQUESTED" and e[1] == "BUY" for e in events)
        assert any(e[0] == "ORDER_RESULT" and e[3] == "FILLED" for e in events)
        assert any(e[2] == "Breakout above opening range" for e in events)
