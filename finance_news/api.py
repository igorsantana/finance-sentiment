"""HTTP API around the pipeline.

Endpoints
---------
GET  /api/dates                List of dates the system knows about.
POST /api/runs                 Start a pipeline run for a given date.
GET  /api/runs/{rid}/stream    Server-Sent-Events stream of a run's logs +
                                progress events. Closes on ``done`` / ``error``.

Concurrency model
-----------------
- One run per UUID. Each run owns a ``RunChannel`` (a thread-safe queue).
- The pipeline executes in a daemon thread; a logging handler scoped to that
  thread (``threading.current_thread()`` filter) routes INFO+ records into
  the channel without bleeding into other concurrent runs.
- The SSE handler ``await``s on the channel via ``run_in_executor`` so the
  asyncio event loop stays responsive.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from finance_news.pipeline import run_full, run_ingest, run_extract
from finance_news.store import db

app = FastAPI(title="Finance News")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for generated images and artifacts
data_dir = Path(__file__).resolve().parent.parent / "data"
data_dir.mkdir(exist_ok=True)
app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")


@dataclass
class RunChannel:
    target_date: str = ""
    kind: str = "full"
    # Append-only event log so a reconnecting client can replay from index 0.
    # Bounded only by run length (a few thousand entries at most) — fine in
    # memory for a single-operator local tool.
    events: list[dict[str, Any]] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)
    finished: bool = False
    status: str = "running"
    error: str | None = None

    def emit(self, ev: dict[str, Any]) -> None:
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    def mark_finished(self) -> None:
        with self.cond:
            self.finished = True
            self.cond.notify_all()


# In-memory only; if uvicorn restarts, in-flight runs are lost. Acceptable
# for a single-operator local tool — if this ever needs to survive restarts
# the truth is already in the `runs` table.
_channels: dict[str, RunChannel] = {}

# At most one pipeline runs at a time. The pipeline fans out to a thread pool
# internally, and filtering log records by `threading.get_ident()` would drop
# every `log.info("==> company …")` emitted from a worker thread. Easier and
# safer to serialize: refuse a second POST /api/runs while one is in flight.
_run_lock = threading.Lock()
_active: tuple[str, "RunChannel"] | None = None  # (run_id, ch)


class _QueueHandler(logging.Handler):
    """Forwards INFO+ records to the active run's queue as structured fields."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)

    def emit(self, record: logging.LogRecord) -> None:
        active = _active
        if active is None:
            return
        try:
            active[1].emit({
                "type": "log",
                "level": record.levelname,
                "logger": record.name.split(".")[-1],
                "ts": record.created,
                "message": record.getMessage(),
            })
        except Exception:
            pass


@contextmanager
def _capture_logs(rid: str, ch: RunChannel) -> Iterator[None]:
    global _active
    _active = (rid, ch)
    handler = _QueueHandler()
    root = logging.getLogger()
    prev_level = root.level
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)
        _active = None


def _run_in_thread(rid: str, ch: RunChannel, target_date: date, kind: str = "full") -> None:
    log = logging.getLogger("api")

    def on_progress(stage: str, current: int, total: int) -> None:
        ch.emit({
            "type": "progress",
            "stage": stage,
            "current": current,
            "total": total,
        })

    with _capture_logs(rid, ch):
        log.info("Starting %s run for %s", kind, target_date)
        try:
            if kind == "ingest":
                summary = run_ingest(target_date=target_date, progress=on_progress, setup_logging=False)
            elif kind == "extract":
                summary = run_extract(target_date=target_date, progress=on_progress, setup_logging=False)
            else:
                summary = run_full(target_date=target_date, progress=on_progress, setup_logging=False)

            ch.status = "ok"
            ch.emit({
                "type": "done",
                "n_fetched": summary.n_fetched,
                "n_extracted": summary.n_extracted,
            })
        except Exception as e:
            ch.status = "error"
            ch.error = repr(e)
            ch.emit({"type": "error", "message": ch.error})
        finally:
            ch.mark_finished()
            _run_lock.release()


# ---------- routes ----------


class StartRunBody(BaseModel):
    date: date
    kind: str = "full"  # "ingest", "extract", or "full"


@app.post("/api/runs")
def start_run(body: StartRunBody) -> dict[str, str]:
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another run is in progress")
    rid = uuid.uuid4().hex
    ch = RunChannel(target_date=body.date.isoformat(), kind=body.kind)
    _channels[rid] = ch
    threading.Thread(
        target=_run_in_thread, args=(rid, ch, body.date, body.kind), daemon=True
    ).start()
    return {"run_id": rid, "stream_url": f"/api/runs/{rid}/stream"}


@app.get("/api/runs/active")
def active_run() -> dict[str, Any] | None:
    """Return the currently in-flight run, or ``null`` if none.

    Used by the web client on page load to reattach to a run that was
    started before the tab was opened (or survived a refresh).
    """
    active = _active
    if active is None:
        return None
    rid, ch = active
    if ch.finished:
        return None
    return {
        "run_id": rid,
        "target_date": ch.target_date,
        "kind": ch.kind,
        "stream_url": f"/api/runs/{rid}/stream",
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    ch = _channels.get(run_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run_id,
        "target_date": ch.target_date,
        "kind": ch.kind,
        "status": ch.status,
        "finished": ch.finished,
        "error": ch.error,
    }


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    ch = _channels.get(run_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def gen():
        # Flush an initial comment so headers go out and the client's
        # EventSource sees the connection open immediately.
        yield ": stream-open\n\n"
        loop = asyncio.get_running_loop()
        idx = 0
        while True:
            batch, finished = await loop.run_in_executor(None, _wait_events, ch, idx, 1.0)
            for msg in batch:
                yield f"data: {json.dumps(msg)}\n\n"
                idx += 1
            if not batch:
                if finished:
                    break
                yield ": ping\n\n"  # SSE comment — keeps proxies awake

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _wait_events(ch: RunChannel, idx: int, timeout: float) -> tuple[list[dict[str, Any]], bool]:
    """Block until at least one event past ``idx`` is available, the run
    finishes, or the timeout elapses. Returns (new_events, finished)."""
    with ch.cond:
        if idx >= len(ch.events) and not ch.finished:
            ch.cond.wait(timeout=timeout)
        return ch.events[idx:], ch.finished


@app.get("/api/dates")
def list_dates() -> dict[str, list[str]]:
    """Return the dates with articles + the dates with rendered output.

    ``processed`` is derived from the filesystem (``data/images/<date>/``) —
    that's what the UI actually wants to surface, and it survives runs that
    were performed via separate ingest/extract steps without a ``full`` row
    in the ``runs`` table.
    All dates are reported in America/Sao_Paulo to match the cron schedule.
    """
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT (published_at AT TIME ZONE 'America/Sao_Paulo')::date AS d
            FROM articles
            WHERE published_at IS NOT NULL
            ORDER BY d
            """
        )
        with_articles = [r["d"].isoformat() for r in cur.fetchall()]

    images_dir = data_dir / "images"
    processed: list[str] = []
    if images_dir.is_dir():
        for child in sorted(images_dir.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "dashboard.png").exists() and not (child / "report.png").exists():
                continue
            try:
                date.fromisoformat(child.name)
            except ValueError:
                continue
            processed.append(child.name)
    return {"processed": processed, "with_articles": with_articles}


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": repr(e)}
