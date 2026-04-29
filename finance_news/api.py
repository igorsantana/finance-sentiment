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
import queue
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from finance_news.pipeline import run_full
from finance_news.store import db

app = FastAPI(title="Finance News")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class RunChannel:
    target_date: str = ""
    q: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    finished: bool = False
    status: str = "running"
    error: str | None = None


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
    """Forwards INFO+ records to the active run's queue."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        active = _active
        if active is None:
            return
        try:
            active[1].q.put({
                "type": "log",
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
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


def _run_in_thread(rid: str, ch: RunChannel, target_date: date) -> None:
    def on_progress(stage: str, current: int, total: int) -> None:
        ch.q.put({
            "type": "progress",
            "stage": stage,
            "current": current,
            "total": total,
        })

    with _capture_logs(rid, ch):
        try:
            summary = run_full(target_date=target_date, progress=on_progress)
            ch.status = "ok"
            ch.q.put({
                "type": "done",
                "n_fetched": summary.n_fetched,
                "n_extracted": summary.n_extracted,
            })
        except Exception as e:
            ch.status = "error"
            ch.error = repr(e)
            ch.q.put({"type": "error", "message": ch.error})
        finally:
            ch.finished = True
            _run_lock.release()


# ---------- routes ----------


class StartRunBody(BaseModel):
    date: date


@app.post("/api/runs")
def start_run(body: StartRunBody) -> dict[str, str]:
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another run is in progress")
    rid = uuid.uuid4().hex
    ch = RunChannel(target_date=body.date.isoformat())
    _channels[rid] = ch
    threading.Thread(
        target=_run_in_thread, args=(rid, ch, body.date), daemon=True
    ).start()
    return {"run_id": rid, "stream_url": f"/api/runs/{rid}/stream"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    ch = _channels.get(run_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run_id,
        "target_date": ch.target_date,
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
        while True:
            msg = await loop.run_in_executor(None, _try_get, ch.q, 1.0)
            if msg is None:
                if ch.finished:
                    break
                yield ": ping\n\n"  # SSE comment — keeps proxies awake
                continue
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("type") in ("done", "error"):
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _try_get(q: "queue.Queue[dict[str, Any]]", timeout: float):
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


@app.get("/api/dates")
def list_dates() -> dict[str, list[str]]:
    """Return the dates with articles + the dates with successful runs.

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
        cur.execute(
            """
            SELECT DISTINCT (started_at AT TIME ZONE 'America/Sao_Paulo')::date AS d
            FROM runs
            WHERE status = 'ok' AND kind = 'full'
            ORDER BY d
            """
        )
        processed = [r["d"].isoformat() for r in cur.fetchall()]
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
