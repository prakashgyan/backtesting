"""Integration tests for dashboard server detail endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from day_trader.dashboard.server import app, configure
from day_trader.run_tracking import RunTracker


def _seed_run(db_path: Path, run_id: str) -> None:
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, started_at_utc, ended_at_utc, status, strategy_name,
                broker_name, data_stream_name, symbol, mode, timeframe,
                metadata_json, initial_capital, bars_processed, trades_executed,
                errors, elapsed_seconds, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "2026-04-12T10:00:00+00:00",
                "2026-04-12T10:30:00+00:00",
                "COMPLETED",
                "day_trader.strategy.examples.simple_sma",
                "SimulatedBroker",
                "ReplayStream",
                "AAPL",
                "replay",
                "1Min",
                "{}",
                100000.0,
                120,
                2,
                0,
                1800.0,
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO run_events (
                run_id, event_time_utc, event_type, symbol, side, qty,
                limit_price, fill_price, status, reason, source, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "2026-04-12T10:02:00+00:00",
                "ORDER_RESULT",
                "AAPL",
                "BUY",
                10.0,
                100.0,
                100.0,
                "FILLED",
                None,
                "test",
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT INTO run_events (
                run_id, event_time_utc, event_type, symbol, side, qty,
                limit_price, fill_price, status, reason, source, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "2026-04-12T10:10:00+00:00",
                "ORDER_RESULT",
                "AAPL",
                "SELL",
                10.0,
                110.0,
                110.0,
                "FILLED",
                None,
                "test",
                "{}",
            ),
        )
    conn.close()


def test_detail_metrics_and_detail_page_routes(tmp_path) -> None:
    db_path = tmp_path / "run_history.db"
    csv_path = tmp_path / "run_metrics.csv"

    tracker = RunTracker(db_path)
    tracker.close()

    _seed_run(db_path, run_id="run-xyz")

    html_path = Path(__file__).resolve().parents[2] / "day_trader" / "dashboard" / "static" / "index.html"
    configure(db_path=db_path, csv_path=csv_path, html_path=html_path)

    client = TestClient(app)

    metrics_res = client.get("/api/runs/run-xyz/detail-metrics")
    assert metrics_res.status_code == 200
    payload = metrics_res.json()
    assert payload["run_id"] == "run-xyz"
    assert payload["filled_orders"] == 2

    page_res = client.get("/runs/run-xyz")
    assert page_res.status_code == 200
    assert "run-xyz" in page_res.text


def test_detail_metrics_404_for_missing_run(tmp_path) -> None:
    db_path = tmp_path / "run_history.db"
    csv_path = tmp_path / "run_metrics.csv"

    tracker = RunTracker(db_path)
    tracker.close()

    html_path = Path(__file__).resolve().parents[2] / "day_trader" / "dashboard" / "static" / "index.html"
    configure(db_path=db_path, csv_path=csv_path, html_path=html_path)

    client = TestClient(app)
    res = client.get("/api/runs/missing/detail-metrics")
    assert res.status_code == 404
