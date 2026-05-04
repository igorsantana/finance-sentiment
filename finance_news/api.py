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
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from finance_news.aggregations import build_report_payload
from finance_news.nlp.companies import load_companies_from_db
from finance_news.pipeline import run_full, run_ingest, run_extract, run_summarize
from finance_news.stocks import fetch_ohlc_window
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
            elif kind == "summarize":
                summary = run_summarize(target_date=target_date, progress=on_progress, setup_logging=False)
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
    """Dates that have at least one article (in America/Sao_Paulo)."""
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
    return {"with_articles": with_articles}


@app.get("/api/reports/{report_date}")
def get_report(report_date: str) -> dict[str, Any]:
    try:
        day = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")
    with db.connect() as conn:
        rows = db.fetch_articles_for_date(conn, day)
    if not rows:
        raise HTTPException(status_code=404, detail="no articles for date")
    sectors_lookup = {
        c["ticker_root"]: {"short_name": c.get("short_name"), "sector": c.get("sector")}
        for c in load_companies_from_db()
    }
    payload = build_report_payload(rows, sectors_lookup)
    payload["date"] = day.isoformat()
    return payload


@app.get("/api/companies/{ticker_root}/summary/{summary_date}")
def get_company_summary(ticker_root: str, summary_date: str) -> dict[str, Any]:
    try:
        day = date.fromisoformat(summary_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")
    root = ticker_root.upper()
    with db.connect() as conn:
        row = db.fetch_company_summary(conn, ticker_root=root, summary_date=day)
        if row is None:
            raise HTTPException(status_code=404, detail="no summary for ticker/date")
        articles = db.fetch_articles_for_company(conn, ticker_root=root, day=day)
    name = next(
        (c.get("short_name") for c in load_companies_from_db() if c["ticker_root"] == root),
        None,
    )
    return {
        "ticker": root,
        "name": name,
        "date": day.isoformat(),
        "good": list(row.get("good_points") or []),
        "bad": list(row.get("bad_points") or []),
        "articleCount": row.get("article_count"),
        "model": row.get("model"),
        "articles": [
            {
                "url": a.get("url"),
                "title": a.get("title"),
                "site": a.get("site"),
                "sentiment": a.get("sentiment"),
                "sentimentScore": (
                    float(a["sentiment_score"]) if a.get("sentiment_score") is not None else None
                ),
            }
            for a in articles[:10]
        ],
    }


@app.get("/api/companies/{ticker_root}/sentiment-series/{series_date}")
def get_sentiment_series(ticker_root: str, series_date: str) -> dict[str, Any]:
    """Per-day sentiment + close price for ±10 trading days around the date,
    plus a Pearson correlation of close vs net sentiment over overlapping days."""
    try:
        day = date.fromisoformat(series_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")
    root = ticker_root.upper()
    with db.connect() as conn:
        bars = fetch_ohlc_window(conn, root, day)
        if not bars:
            return {
                "ticker": root,
                "selectedDate": day.isoformat(),
                "points": [],
                "correlation": None,
            }
        start = bars[0]["bar_date"]
        end = bars[-1]["bar_date"]
        sentiment_rows = db.fetch_sentiment_series(
            conn, ticker_root=root, start=start, end=end
        )

    by_day = {r["day"]: r for r in sentiment_rows}
    points: list[dict[str, Any]] = []
    closes: list[float] = []
    nets: list[float] = []
    for b in bars:
        bd = b["bar_date"]
        s = by_day.get(bd)
        pos = int(s["positive"]) if s else 0
        neu = int(s["neutral"]) if s else 0
        neg = int(s["negative"]) if s else 0
        total = pos + neu + neg
        net = (pos - neg) / total if total else 0.0
        avg_score = float(s["avg_score"]) if s and s.get("avg_score") is not None else None
        close = float(b["close"])
        if total > 0:
            closes.append(close)
            nets.append(net)
        points.append({
            "date": bd.isoformat(),
            "close": close,
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "total": total,
            "net": net,
            "avgScore": avg_score,
        })

    return {
        "ticker": root,
        "selectedDate": day.isoformat(),
        "points": points,
        "correlation": _pearson(closes, nets),
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    if dx2 == 0 or dy2 == 0:
        return None
    return num / (dx2**0.5 * dy2**0.5)


@app.get("/api/stocks/{ticker_root}/ohlc/{ohlc_date}")
def get_stock_ohlc(ticker_root: str, ohlc_date: str) -> dict[str, Any]:
    try:
        day = date.fromisoformat(ohlc_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")
    root = ticker_root.upper()
    with db.connect() as conn:
        bars = fetch_ohlc_window(conn, root, day)
    return {
        "ticker": root,
        "selectedDate": day.isoformat(),
        "bars": [
            {
                "date": b["bar_date"].isoformat(),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": b.get("volume"),
            }
            for b in bars
        ],
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": repr(e)}
