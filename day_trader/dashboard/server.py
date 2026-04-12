"""FastAPI dashboard server for day-trader run history."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import fastapi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from day_trader.dashboard import queries
from day_trader.dashboard.models import (
    BenchmarkSeries,
    PnLPoint,
    RunDetail,
    RunDetailMetrics,
    RunEvent,
    RunSummary,
    SummaryStats,
)

app = FastAPI(title="Day Trader Dashboard", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "DELETE"],
    allow_headers=["*"],
)

_HTML_STATE: dict[str, str] = {
    "index": "",
    "detail": "",
}


def configure(db_path: Path, csv_path: Path, html_path: Path) -> None:
    """Set paths and load the HTML file. Call once before uvicorn starts."""
    queries.configure_paths(db_path, csv_path)
    _HTML_STATE["index"] = html_path.read_text(encoding="utf-8")
    detail_path = html_path.parent / "run_detail.html"
    _HTML_STATE["detail"] = detail_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> HTMLResponse:
    return HTMLResponse(content=_HTML_STATE["index"])


@app.get("/runs/{run_id}", response_class=HTMLResponse, include_in_schema=False)
async def run_detail_page(run_id: str) -> HTMLResponse:
    page = _HTML_STATE["detail"].replace("__RUN_ID__", run_id)
    return HTMLResponse(content=page)


@app.get("/api/summary", response_model=SummaryStats)
async def get_summary() -> SummaryStats:
    data: dict[str, Any] = await asyncio.to_thread(queries.fetch_summary)
    return SummaryStats(**data)


@app.get("/api/runs", response_model=list[RunSummary])
async def get_runs() -> list[RunSummary]:
    rows: list[dict[str, Any]] = await asyncio.to_thread(queries.fetch_runs)
    return [RunSummary(**r) for r in rows]


@app.get("/api/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str) -> RunDetail:
    row: dict[str, Any] | None = await asyncio.to_thread(queries.fetch_run, run_id)
    if row is None:
        raise fastapi.HTTPException(status_code=404, detail="Run not found")
    return RunDetail(**row)


@app.get("/api/runs/{run_id}/events", response_model=list[RunEvent])
async def get_events(run_id: str) -> list[RunEvent]:
    rows: list[dict[str, Any]] = await asyncio.to_thread(queries.fetch_events, run_id)
    return [RunEvent(**r) for r in rows]


@app.get("/api/runs/{run_id}/pnl", response_model=list[PnLPoint])
async def get_pnl(run_id: str) -> list[PnLPoint]:
    rows: list[dict[str, Any]] = await asyncio.to_thread(
        queries.compute_pnl_series, run_id
    )
    return [PnLPoint(**r) for r in rows]


@app.get("/api/runs/{run_id}/detail-metrics", response_model=RunDetailMetrics)
async def get_run_detail_metrics(run_id: str) -> RunDetailMetrics:
    row: dict[str, Any] | None = await asyncio.to_thread(
        queries.fetch_run_detail_metrics, run_id
    )
    if row is None:
        raise fastapi.HTTPException(status_code=404, detail="Run not found")
    return RunDetailMetrics(**row)


@app.get("/api/runs/{run_id}/benchmarks", response_model=BenchmarkSeries)
async def get_benchmarks(run_id: str) -> BenchmarkSeries:
    row: dict[str, Any] | None = await asyncio.to_thread(
        queries.fetch_benchmark_series, run_id
    )
    if row is None:
        raise fastapi.HTTPException(status_code=404, detail="Run not found")
    return BenchmarkSeries(**row)


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str) -> dict[str, str]:
    """Delete a run and its events."""
    deleted: bool = await asyncio.to_thread(queries.delete_run, run_id)
    if not deleted:
        raise fastapi.HTTPException(status_code=404, detail="Run not found")
    return {"status": "deleted", "run_id": run_id}
