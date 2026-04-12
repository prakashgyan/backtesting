"""Run and event tracking abstractions with a SQLite-backed implementation."""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from day_trader.models import Order


class EventStoreInterface(ABC):
    """Abstract interface for persisting run lifecycle and order events.

    Decouples the Engine and Strategy from any specific storage backend.
    Implementations include SQLite (RunTracker) and a no-op for tests
    (NullEventStore).
    """

    @abstractmethod
    def start_run(
        self,
        strategy_name: str,
        broker_name: str,
        data_stream_name: str,
        initial_capital: float,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Start a new run record and return its run_id."""
        ...

    @abstractmethod
    def log_event(
        self,
        event_type: str,
        source: str,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        qty: Optional[float] = None,
        limit_price: Optional[float] = None,
        fill_price: Optional[float] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None: ...

    @abstractmethod
    def log_order_request(
        self,
        symbol: str,
        side: str,
        qty: float,
        limit_price: Optional[float],
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None: ...

    @abstractmethod
    def log_order_result(
        self,
        order: Order,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None: ...

    @abstractmethod
    def log_order_error(
        self,
        symbol: str,
        side: str,
        qty: float,
        limit_price: Optional[float],
        error: str,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None: ...

    @abstractmethod
    def complete_run(
        self,
        status: str,
        bars_processed: int,
        trades_executed: int,
        errors: int,
        elapsed_seconds: float,
        error_message: Optional[str] = None,
    ) -> None: ...

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by this store."""
        ...


class NullEventStore(EventStoreInterface):
    """No-op event store for use in tests or when persistence is disabled."""

    def start_run(self, strategy_name: str, broker_name: str, data_stream_name: str,
                  initial_capital: float, metadata: Optional[dict[str, Any]] = None) -> str:
        return ""

    def log_event(self, event_type: str, source: str, **kwargs: Any) -> None:
        pass

    def log_order_request(self, symbol: str, side: str, qty: float,
                          limit_price: Optional[float], reason: Optional[str] = None,
                          details: Optional[dict[str, Any]] = None,
                          event_time: Optional[datetime] = None) -> None:
        pass

    def log_order_result(self, order: Order, reason: Optional[str] = None,
                         details: Optional[dict[str, Any]] = None,
                         event_time: Optional[datetime] = None) -> None:
        pass

    def log_order_error(self, symbol: str, side: str, qty: float,
                        limit_price: Optional[float], error: str,
                        reason: Optional[str] = None,
                        details: Optional[dict[str, Any]] = None,
                        event_time: Optional[datetime] = None) -> None:
        pass

    def complete_run(self, status: str, bars_processed: int, trades_executed: int,
                     errors: int, elapsed_seconds: float,
                     error_message: Optional[str] = None) -> None:
        pass

    def close(self) -> None:
        pass


class RunTracker(EventStoreInterface):
    """Persist run lifecycle and order events to SQLite.

    This tracker is intentionally strategy-agnostic. Strategies can emit
    optional reason/details fields, while the tracker stores a uniform schema.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._run_id: Optional[str] = None
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started_at_utc TEXT NOT NULL,
                    ended_at_utc TEXT,
                    status TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    broker_name TEXT NOT NULL,
                    data_stream_name TEXT NOT NULL,
                    symbol TEXT,
                    mode TEXT,
                    timeframe TEXT,
                    metadata_json TEXT,
                    initial_capital REAL NOT NULL,
                    bars_processed INTEGER DEFAULT 0,
                    trades_executed INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    elapsed_seconds REAL DEFAULT 0,
                    error_message TEXT,
                    data_start_date TEXT,
                    data_end_date TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_time_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    side TEXT,
                    qty REAL,
                    limit_price REAL,
                    fill_price REAL,
                    status TEXT,
                    reason TEXT,
                    source TEXT,
                    details_json TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs (run_id)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events (run_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_events_time ON run_events (event_time_utc)"
            )
            # Migrate existing databases: add data_start_date and data_end_date columns
            try:
                self._conn.execute("ALTER TABLE runs ADD COLUMN data_start_date TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                self._conn.execute("ALTER TABLE runs ADD COLUMN data_end_date TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

    @staticmethod
    def _now_utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_json(data: Optional[dict[str, Any]]) -> str:
        if not data:
            return "{}"
        return json.dumps(data, default=str, sort_keys=True)

    def start_run(
        self,
        strategy_name: str,
        broker_name: str,
        data_stream_name: str,
        initial_capital: float,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        run_id = str(uuid4())
        metadata = metadata or {}

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO runs (
                    run_id,
                    started_at_utc,
                    status,
                    strategy_name,
                    broker_name,
                    data_stream_name,
                    symbol,
                    mode,
                    timeframe,
                    metadata_json,
                    initial_capital,
                    data_start_date,
                    data_end_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    self._now_utc_iso(),
                    "RUNNING",
                    strategy_name,
                    broker_name,
                    data_stream_name,
                    metadata.get("symbol"),
                    metadata.get("mode"),
                    metadata.get("timeframe"),
                    self._to_json(metadata),
                    float(initial_capital),
                    metadata.get("data_start_date"),
                    metadata.get("data_end_date"),
                ),
            )

        self._run_id = run_id
        self.log_event(
            event_type="RUN_STARTED",
            source="engine",
            details={
                "strategy_name": strategy_name,
                "broker_name": broker_name,
                "data_stream_name": data_stream_name,
            },
        )
        return run_id

    def log_event(
        self,
        event_type: str,
        source: str,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        qty: Optional[float] = None,
        limit_price: Optional[float] = None,
        fill_price: Optional[float] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None:
        if not self._run_id:
            return

        # Use provided event_time (e.g., bar timestamp in replay mode) or wall-clock time
        timestamp = event_time.isoformat() if event_time else self._now_utc_iso()

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO run_events (
                    run_id,
                    event_time_utc,
                    event_type,
                    symbol,
                    side,
                    qty,
                    limit_price,
                    fill_price,
                    status,
                    reason,
                    source,
                    details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    timestamp,
                    event_type,
                    symbol,
                    side,
                    qty,
                    limit_price,
                    fill_price,
                    status,
                    reason,
                    source,
                    self._to_json(details),
                ),
            )

    def log_order_request(
        self,
        symbol: str,
        side: str,
        qty: float,
        limit_price: Optional[float],
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None:
        self.log_event(
            event_type="ORDER_REQUESTED",
            source="strategy",
            symbol=symbol,
            side=side,
            qty=qty,
            limit_price=limit_price,
            reason=reason,
            details=details,
            event_time=event_time,
        )

    def log_order_result(
        self,
        order: Order,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None:
        self.log_event(
            event_type="ORDER_RESULT",
            source="broker",
            symbol=order.symbol,
            side=order.side.value,
            qty=order.qty,
            limit_price=order.avg_fill_price if order.avg_fill_price > 0 else None,
            fill_price=order.avg_fill_price if order.avg_fill_price > 0 else None,
            status=order.status.value,
            reason=reason,
            details=details,
            event_time=event_time,
        )

    def log_order_error(
        self,
        symbol: str,
        side: str,
        qty: float,
        limit_price: Optional[float],
        error: str,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> None:
        payload = dict(details or {})
        payload["error"] = error
        self.log_event(
            event_type="ORDER_FAILED",
            source="broker",
            symbol=symbol,
            side=side,
            qty=qty,
            limit_price=limit_price,
            status="REJECTED",
            reason=reason,
            details=payload,
            event_time=event_time,
        )

    def complete_run(
        self,
        status: str,
        bars_processed: int,
        trades_executed: int,
        errors: int,
        elapsed_seconds: float,
        error_message: Optional[str] = None,
    ) -> None:
        if not self._run_id:
            return

        with self._conn:
            self._conn.execute(
                """
                UPDATE runs
                SET
                    ended_at_utc = ?,
                    status = ?,
                    bars_processed = ?,
                    trades_executed = ?,
                    errors = ?,
                    elapsed_seconds = ?,
                    error_message = ?
                WHERE run_id = ?
                """,
                (
                    self._now_utc_iso(),
                    status,
                    bars_processed,
                    trades_executed,
                    errors,
                    float(elapsed_seconds),
                    error_message,
                    self._run_id,
                ),
            )

        self.log_event(
            event_type="RUN_COMPLETED",
            source="engine",
            status=status,
            details={
                "bars_processed": bars_processed,
                "trades_executed": trades_executed,
                "errors": errors,
                "elapsed_seconds": elapsed_seconds,
                "error_message": error_message,
            },
        )

    def close(self) -> None:
        self._conn.close()