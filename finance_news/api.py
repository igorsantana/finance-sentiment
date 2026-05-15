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
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterator, Optional

import requests as _requests

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from finance_news.aggregations import build_report_payload, build_window_payload
from finance_news.nlp.companies import load_companies_from_db
from finance_news.pipeline import run_cvm_ingest, run_full, run_ingest, run_extract, run_summarize
from finance_news.stocks import fetch_ohlc_trailing, fetch_ohlc_window
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
    stop_event: threading.Event = field(default_factory=threading.Event)

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

    def _check_stop() -> None:
        if ch.stop_event.is_set():
            raise InterruptedError("cancelled")

    with _capture_logs(rid, ch):
        log.info("Starting %s run for %s", kind, target_date)
        try:
            if kind == "ingest":
                summary = run_ingest(target_date=target_date, progress=on_progress, setup_logging=False)
            elif kind == "extract":
                summary = run_extract(target_date=target_date, progress=on_progress, setup_logging=False)
            elif kind == "summarize":
                summary = run_summarize(target_date=target_date, progress=on_progress, setup_logging=False)
            elif kind == "cvm":
                summary = run_cvm_ingest(target_date=target_date, progress=on_progress, setup_logging=False)
            else:
                ingest_s = run_ingest(target_date=target_date, progress=on_progress, setup_logging=False)
                _check_stop()
                extract_s = run_extract(target_date=target_date, progress=on_progress, setup_logging=False)
                _check_stop()
                summarize_s = run_summarize(target_date=target_date, progress=on_progress, setup_logging=False)
                from finance_news.pipeline import RunSummary
                summary = RunSummary(
                    kind="full", run_id=ingest_s.run_id,
                    started_at=ingest_s.started_at,
                    n_fetched=ingest_s.n_fetched + extract_s.n_fetched,
                    n_extracted=extract_s.n_extracted + summarize_s.n_extracted,
                    status="ok",
                )

            ch.status = "ok"
            ch.emit({
                "type": "done",
                "n_fetched": summary.n_fetched,
                "n_extracted": summary.n_extracted,
            })
        except InterruptedError:
            ch.status = "cancelled"
            log.info("Run %s was cancelled by the user.", rid)
            ch.emit({"type": "error", "message": "Execução cancelada pelo usuário."})
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
    kind: str = "full"  # "ingest", "extract", "summarize", "cvm", or "full"


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


@app.delete("/api/runs/{run_id}")
def cancel_run(run_id: str) -> dict[str, str]:
    ch = _channels.get(run_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="run not found")
    if ch.finished:
        raise HTTPException(status_code=409, detail="run already finished")
    ch.stop_event.set()
    return {"status": "cancelling"}


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


def _today_sp_date() -> date:
    """Today in São Paulo (matches how articles' SP-day is computed)."""
    from datetime import datetime, timezone
    sp = datetime.now(timezone.utc).astimezone()
    # Postgres queries already cast to America/Sao_Paulo; do the same here.
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def _yfinance_snapshot(symbol: str) -> Optional[dict[str, float]]:
    """Return ``{price, open, prev_close}`` for a yfinance symbol or ``None``.

    Used for indices like ``^BVSP`` where the daily history endpoint
    occasionally returns a malformed bar (open=0) for the current
    session. ``fast_info`` exposes the same numbers as ``info`` without
    the extra HTTP roundtrips.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        fi = yf.Ticker(symbol).fast_info
    except Exception:
        return None

    def _read(*names: str) -> Optional[float]:
        for n in names:
            try:
                v = fi[n] if n in fi else getattr(fi, n, None)  # type: ignore[index]
            except Exception:
                v = None
            if v is None:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f > 0:
                return f
        return None

    price = _read("last_price", "lastPrice", "regular_market_previous_close")
    if price is None:
        return None
    return {
        "price": price,
        "open": _read("open"),
        "prev_close": _read("previous_close", "previousClose", "regular_market_previous_close"),
    }


def _intraday_change_pct(
    snapshot: dict[str, float],
    cached_prev_close: Optional[float] = None,
) -> Optional[float]:
    """Convert a live snapshot to a daily-return percentage.

    Prefers the open-to-current move (matches what we report for past
    days). Falls back to previous-close-to-current when the snapshot
    itself can't supply a good open. ``cached_prev_close`` lets the
    caller provide yesterday's settled close from the OHLC cache when
    the live source doesn't expose it.
    """
    price = snapshot.get("price")
    if not price:
        return None
    open_ = snapshot.get("open")
    if open_ and open_ > 0:
        return (price - open_) / open_ * 100
    prev = snapshot.get("prev_close") or cached_prev_close
    if prev and prev > 0:
        return (price - prev) / prev * 100
    return None


@app.get("/api/calendar")
def get_calendar(
    month: str,
    tickers: str = Query(default=""),
    quantities: str = Query(default=""),
) -> dict[str, Any]:
    """Calendar metadata for a given month.

    ``month`` must be ``YYYY-MM``.  Returns per-day entries covering every day
    in the month, including weekends.  Optional ``tickers`` (comma-separated)
    and ``quantities`` (comma-separated floats) enable per-day portfolio return.

    For *today's* row specifically, when the cached daily bars are
    missing (yfinance hasn't published the settled bar yet) we fall back
    to a live snapshot — yfinance's ``fast_info`` for ``^BVSP`` and
    BrAPI for portfolio tickers — so the operator sees a meaningful
    intraday number instead of an empty cell.
    """
    import calendar as _calendar
    try:
        year, mo = (int(p) for p in month.split("-"))
        _, last_day = _calendar.monthrange(year, mo)
        start = date(year, mo, 1)
        end = date(year, mo, last_day)
    except Exception:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    try:
        qty_list = [float(q) for q in quantities.split(",") if q.strip()]
    except ValueError:
        qty_list = []
    while len(qty_list) < len(ticker_list):
        qty_list.append(1.0)

    fetch_days = (end - start).days + 10
    with db.connect() as conn:
        sentiment_rows = db.fetch_calendar_sentiment(conn, start=start, end=end)
        ibov_bars = fetch_ohlc_trailing(conn, "^BVSP", end, days=fetch_days)
        portfolio_bars: dict[str, dict] = {}
        for ticker in ticker_list:
            bars = fetch_ohlc_trailing(conn, ticker, end, days=fetch_days)
            portfolio_bars[ticker] = {b["bar_date"]: b for b in bars}

        # Resolve ticker_root → full ".SA" symbol once, for the BrAPI fallback.
        root_to_full: dict[str, str] = {}
        if ticker_list:
            for c in load_companies_from_db():
                if c["ticker_root"] in ticker_list:
                    root_to_full[c["ticker_root"]] = c["ticker"]

    by_day = {r["day"]: r for r in sentiment_rows}
    ibov_by_day = {b["bar_date"]: b for b in ibov_bars}

    today_sp = _today_sp_date()
    needs_today_fallback = start <= today_sp <= end

    # ---------- live-snapshot fallback for the "today" row only ----------
    ibov_today_snapshot: Optional[dict[str, float]] = None
    portfolio_today_quotes: dict[str, dict] = {}
    if needs_today_fallback:
        if ibov_by_day.get(today_sp) is None:
            ibov_today_snapshot = _yfinance_snapshot("^BVSP")
        missing_portfolio_today = ticker_list and any(
            portfolio_bars.get(t, {}).get(today_sp) is None for t in ticker_list
        )
        if missing_portfolio_today and root_to_full:
            full_syms = [root_to_full[t] for t in ticker_list if t in root_to_full]
            portfolio_today_quotes = _brapi_quotes(full_syms)

    def _prev_close_for(ticker_root: str, day: date) -> Optional[float]:
        bars = portfolio_bars.get(ticker_root, {}) if ticker_root != "^BVSP" else ibov_by_day
        prev_dates = sorted(d for d in bars if d < day)
        if not prev_dates:
            return None
        prev = bars[prev_dates[-1]]
        return float(prev["close"]) if prev.get("close") is not None else None

    days = []
    cur = start
    while cur <= end:
        s = by_day.get(cur)
        ibov = ibov_by_day.get(cur)
        pos = int(s["positive"]) if s else 0
        neg = int(s["negative"]) if s else 0
        total = int(s["article_count"]) if s else 0
        sentiment_net = (pos - neg) / total if total else None
        ibov_change = (
            float(ibov["close"] - ibov["open"]) / float(ibov["open"]) * 100
            if ibov and ibov.get("open") and float(ibov["open"]) != 0
            else None
        )
        if ibov_change is None and cur == today_sp and ibov_today_snapshot:
            ibov_change = _intraday_change_pct(
                ibov_today_snapshot,
                cached_prev_close=_prev_close_for("^BVSP", today_sp),
            )

        # Portfolio return: quantity-weighted average of intraday returns.
        portfolio_change: float | None = None
        if ticker_list:
            weighted, weight_sum = 0.0, 0.0
            for ticker, qty in zip(ticker_list, qty_list):
                bar = portfolio_bars.get(ticker, {}).get(cur)
                if bar and bar.get("open") and float(bar["open"]) != 0:
                    day_ret = float(bar["close"] - bar["open"]) / float(bar["open"])
                    weighted += day_ret * qty
                    weight_sum += qty
                elif cur == today_sp:
                    full = root_to_full.get(ticker)
                    quote = portfolio_today_quotes.get(full) if full else None
                    if quote:
                        ret_pct = _intraday_change_pct(
                            {
                                "price": quote.get("price"),
                                "open": quote.get("open"),
                                "prev_close": None,
                            },
                            cached_prev_close=_prev_close_for(ticker, today_sp),
                        )
                        if ret_pct is not None:
                            weighted += (ret_pct / 100) * qty
                            weight_sum += qty
            if weight_sum > 0:
                portfolio_change = weighted / weight_sum * 100

        days.append({
            "date": cur.isoformat(),
            "has_articles": bool(s),
            "article_count": total,
            "sentiment_net": round(sentiment_net, 4) if sentiment_net is not None else None,
            "positive_pct": round(pos / total * 100, 1) if total else None,
            "negative_pct": round(neg / total * 100, 1) if total else None,
            "ibovespa_change_pct": round(ibov_change, 2) if ibov_change is not None else None,
            "portfolio_change_pct": round(portfolio_change, 2) if portfolio_change is not None else None,
        })
        cur = cur.fromordinal(cur.toordinal() + 1)

    return {"month": month, "days": days}


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


_WINDOW_OPTIONS = (1, 3, 7, 14)


def _subtract_business_days(d: date, n: int) -> date:
    """Return the date that is ``n`` business days (Mon–Fri) before ``d``."""
    current = d
    while n > 0:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            n -= 1
    return current


def _resolve_window(window: int, end: str | None) -> tuple[date, date, int]:
    if window not in _WINDOW_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"window must be one of {list(_WINDOW_OPTIONS)}",
        )
    if end is None:
        with db.connect() as conn:
            end_date = db.latest_article_date(conn)
        if end_date is None:
            raise HTTPException(status_code=404, detail="no articles in DB")
    else:
        try:
            end_date = date.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid end date")
    # Advance end_date to the nearest weekday if it lands on a weekend
    while end_date.weekday() >= 5:
        end_date -= timedelta(days=1)
    start_date = _subtract_business_days(end_date, window - 1)
    return start_date, end_date, window


@app.get("/api/trends/overall")
def get_trends_overall(
    window: int = 7,
    end: str | None = None,
    tickers: str | None = None,
) -> dict[str, Any]:
    start_date, end_date, days = _resolve_window(window, end)
    ticker_list = (
        [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if tickers
        else None
    )
    with db.connect() as conn:
        rows = db.fetch_articles_in_window(
            conn, start=start_date, end=end_date, ticker_roots=ticker_list or None
        )
    if not rows:
        raise HTTPException(status_code=404, detail="no articles in window")
    sectors_lookup = {
        c["ticker_root"]: {"short_name": c.get("short_name"), "sector": c.get("sector")}
        for c in load_companies_from_db()
    }
    return build_window_payload(rows, sectors_lookup, start=start_date, end=end_date)


@app.get("/api/trends/company/{ticker_root}")
def get_trends_company(
    ticker_root: str,
    window: int = 7,
    end: str | None = None,
) -> dict[str, Any]:
    start_date, end_date, days = _resolve_window(window, end)
    root = ticker_root.upper()
    name = next(
        (c.get("short_name") for c in load_companies_from_db() if c["ticker_root"] == root),
        None,
    )
    if name is None:
        raise HTTPException(status_code=404, detail="unknown ticker")

    with db.connect() as conn:
        sentiment_rows = db.fetch_daily_sentiment_window(
            conn, start=start_date, end=end_date, ticker_root=root,
        )
        articles = db.fetch_articles_in_window(
            conn, start=start_date, end=end_date, ticker_root=root,
        )
        bars = fetch_ohlc_trailing(conn, root, end_date, days=days)

    if not articles and not bars:
        raise HTTPException(status_code=404, detail="no data in window")

    by_day = {r["day"]: r for r in sentiment_rows}
    closes_by_day = {b["bar_date"]: float(b["close"]) for b in bars}

    daily: list[dict[str, Any]] = []
    closes: list[float] = []
    nets: list[float] = []
    # Iterate calendar days but emit only business days
    cal_days = (end_date - start_date).days + 1
    for offset in range(cal_days):
        d = start_date + timedelta(days=offset)
        if d.weekday() >= 5:  # skip Saturday / Sunday
            continue
        s = by_day.get(d)
        pos = int(s["positive"]) if s else 0
        neu = int(s["neutral"]) if s else 0
        neg = int(s["negative"]) if s else 0
        total = pos + neu + neg
        net = (pos - neg) / total if total else 0.0
        avg_score = (
            float(s["avg_score"]) if s and s.get("avg_score") is not None else None
        )
        close = closes_by_day.get(d)
        if total > 0 and close is not None:
            closes.append(close)
            nets.append(net)
        daily.append({
            "date": d.isoformat(),
            "positive": pos, "neutral": neu, "negative": neg,
            "total": total, "net": net,
            "avgScore": avg_score,
            "close": close,
        })

    from collections import Counter as _Counter, defaultdict as _defaultdict
    publisher_sentiment: dict[str, _Counter] = _defaultdict(_Counter)
    subject_counts: dict[str, int] = {}
    by_sentiment = {"positive": 0, "neutral": 0, "negative": 0}
    for a in articles:
        sent = a.get("sentiment")
        if sent in by_sentiment:
            by_sentiment[sent] += 1
        site = a.get("site")
        if site and sent in by_sentiment:
            publisher_sentiment[site][sent] += 1
        elif site:
            publisher_sentiment[site]  # ensure key exists
        for sub in (a.get("subjects") or []):
            subject_counts[sub] = subject_counts.get(sub, 0) + 1

    sentiment_by_publisher = sorted(
        [
            {
                "site": site,
                "positive": c["positive"],
                "neutral": c["neutral"],
                "negative": c["negative"],
                "total": c["positive"] + c["neutral"] + c["negative"],
            }
            for site, c in publisher_sentiment.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )[:10]
    top_subjects = sorted(
        ({"subject": k, "count": v} for k, v in subject_counts.items()),
        key=lambda x: x["count"], reverse=True,
    )[:10]

    return {
        "ticker": root,
        "name": name,
        "window": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days,
        },
        "counts": {"total": len(articles), "bySentiment": by_sentiment},
        "daily": daily,
        "sentimentByPublisher": sentiment_by_publisher,
        "topSubjects": top_subjects,
        "correlation": _pearson(closes, nets),
    }


@app.get("/api/advisor/overall")
def get_advisor_overall(window: int = 7, end: str | None = None, tickers: str | None = None) -> dict[str, Any]:
    payload = get_trends_overall(window=window, end=end, tickers=tickers)
    end_iso = payload["window"]["end"]
    end_date = date.fromisoformat(end_iso)
    days = payload["window"]["days"]

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else []
    cache_key = ",".join(sorted(ticker_list)) if ticker_list else ""

    with db.connect() as conn:
        cached = db.fetch_advisor_narrative(
            conn, window_days=days, end_date=end_date, ticker_root=cache_key,
        )
    if cached:
        return _serialize_narrative(cached)

    from finance_news.nlp.advisor import summarize_market_window
    result = summarize_market_window(
        window_days=days, end=end_iso,
        daily=payload["daily"],
        top_companies=payload["topCompanies"],
        sector_matrix=payload["sectorMatrix"],
    )
    if result is None:
        raise HTTPException(status_code=503, detail="advisor unavailable")

    article_count = payload["counts"]["total"]
    with db.connect() as conn:
        db.upsert_advisor_narrative(
            conn,
            window_days=days, end_date=end_date, ticker_root=cache_key,
            paragraphs=result["paragraphs"],
            article_count=article_count,
            model=result["model"],
        )
    return {
        "paragraphs": result["paragraphs"],
        "articleCount": article_count,
        "model": result["model"],
        "generatedAt": _now_iso(),
    }


@app.get("/api/advisor/company/{ticker_root}")
def get_advisor_company(
    ticker_root: str,
    window: int = 7,
    end: str | None = None,
) -> dict[str, Any]:
    payload = get_trends_company(ticker_root=ticker_root, window=window, end=end)
    end_iso = payload["window"]["end"]
    end_date = date.fromisoformat(end_iso)
    days = payload["window"]["days"]
    root = payload["ticker"]

    with db.connect() as conn:
        cached = db.fetch_advisor_narrative(
            conn, window_days=days, end_date=end_date, ticker_root=root,
        )
    if cached:
        return _serialize_narrative(cached)

    from finance_news.nlp.advisor import summarize_company_window
    result = summarize_company_window(
        ticker=root, name=payload["name"],
        window_days=days, end=end_iso,
        daily=payload["daily"],
        correlation=payload["correlation"],
        top_subjects=payload["topSubjects"],
    )
    if result is None:
        raise HTTPException(status_code=503, detail="advisor unavailable")

    article_count = payload["counts"]["total"]
    with db.connect() as conn:
        db.upsert_advisor_narrative(
            conn,
            window_days=days, end_date=end_date, ticker_root=root,
            paragraphs=result["paragraphs"],
            article_count=article_count,
            model=result["model"],
        )
    return {
        "paragraphs": result["paragraphs"],
        "articleCount": article_count,
        "model": result["model"],
        "generatedAt": _now_iso(),
    }


def _serialize_narrative(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "paragraphs": list(row["paragraphs"]),
        "articleCount": row["article_count"],
        "model": row["model"],
        "generatedAt": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


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


@app.get("/api/companies/{ticker_root}/social-sentiment/{series_date}")
def get_social_sentiment_series(ticker_root: str, series_date: str) -> dict[str, Any]:
    """Per-day X/social post sentiment counts for a ticker (±10 calendar days)."""
    try:
        day = date.fromisoformat(series_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")
    root = ticker_root.upper()
    start = day - timedelta(days=10)
    end = day + timedelta(days=10)
    with db.connect() as conn:
        rows = db.fetch_social_sentiment_series(
            conn, ticker_root=root, start=start, end=end,
        )
    points: list[dict[str, Any]] = []
    for r in rows:
        pos = int(r["positive"])
        neg = int(r["negative"])
        neu = int(r["neutral"])
        total = int(r["total"])
        net = (pos - neg) / total if total else 0.0
        points.append({
            "date": r["day"].isoformat(),
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "total": total,
            "net": net,
        })
    return {
        "ticker": root,
        "selectedDate": day.isoformat(),
        "platform": "x",
        "points": points,
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


@app.get("/api/companies")
def list_companies() -> list[dict[str, Any]]:
    """All tracked companies sorted by market cap desc."""
    return [
        {
            "tickerRoot": c["ticker_root"],
            "ticker": c["ticker"],
            "shortName": c.get("short_name"),
            "longName": c.get("long_name"),
            "sector": c.get("sector"),
            "marketCap": c.get("market_cap"),
        }
        for c in load_companies_from_db()
    ]


@app.get("/api/portfolio/snapshot")
def get_portfolio_snapshot(
    tickers: str = "",
    windows: str = "3,7,14",
) -> list[dict[str, Any]]:
    """Current close, day open, and window gain/loss % for a list of tickers.

    ``tickers`` — comma-separated ticker roots (e.g. ``PETR,VALE``).
    ``windows`` — comma-separated subset of {3,7,14}.
    Unknown tickers are included with all values ``null``.
    """
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers is required")

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:30]

    try:
        window_list = [int(w.strip()) for w in windows.split(",") if w.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid windows parameter")
    if not all(w in _WINDOW_OPTIONS for w in window_list):
        raise HTTPException(
            status_code=400,
            detail=f"windows must be a subset of {list(_WINDOW_OPTIONS)}",
        )

    companies_map = {
        c["ticker_root"]: c for c in load_companies_from_db()
    }

    with db.connect() as conn:
        end_date = db.latest_article_date(conn) or date.today()

    results: list[dict[str, Any]] = []
    with db.connect() as conn:
        for root in ticker_list:
            bars = fetch_ohlc_trailing(conn, root, end_date, days=20)
            comp = companies_map.get(root)
            if not bars:
                results.append({
                    "tickerRoot": root,
                    "ticker": comp["ticker"] if comp else root,
                    "shortName": comp.get("short_name") if comp else None,
                    "currentClose": None,
                    "dayOpen": None,
                    "changes": {str(w): None for w in window_list},
                    "asOf": end_date.isoformat(),
                })
                continue

            last_bar = bars[-1]
            current_close = float(last_bar["close"])
            day_open = float(last_bar["open"])

            changes: dict[str, float | None] = {}
            for w in window_list:
                cutoff = end_date - timedelta(days=w)
                ref_bar = next(
                    (b for b in reversed(bars) if b["bar_date"] <= cutoff),
                    None,
                )
                if ref_bar is None:
                    changes[str(w)] = None
                else:
                    ref_close = float(ref_bar["close"])
                    changes[str(w)] = (
                        (current_close - ref_close) / ref_close * 100
                        if ref_close != 0 else None
                    )

            results.append({
                "tickerRoot": root,
                "ticker": comp["ticker"] if comp else root,
                "shortName": comp.get("short_name") if comp else None,
                "currentClose": current_close,
                "dayOpen": day_open,
                "changes": changes,
                "asOf": last_bar["bar_date"].isoformat(),
            })

    return results


@app.get("/api/companies/dates")
def get_companies_dates(tickers: str = "") -> dict[str, list[str]]:
    """SP-dates that have ≥1 article for any of the given tickers.

    ``tickers`` — comma-separated ticker roots. Returns ``{ dates: [...] }``
    sorted descending. Used by the sidebar portfolio filter.
    """
    if not tickers:
        return {"dates": []}
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:30]

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT (published_at AT TIME ZONE 'America/Sao_Paulo')::date AS d
            FROM articles
            WHERE published_at IS NOT NULL
              AND matched_tickers && %s::text[]
            ORDER BY d DESC
            """,
            (ticker_list,),
        )
        dates = [r["d"].isoformat() for r in cur.fetchall()]
    return {"dates": dates}


_BRAPI_QUOTE_URL = "https://brapi.dev/api/quote/"
_BRAPI_WORKERS = 8  # concurrent requests for the live stream


def _brapi_quotes(full_tickers: list[str]) -> dict[str, dict]:
    """Fetch near-realtime prices from BrAPI for a list of full ticker symbols.

    Free tier only accepts one ticker per request, so we fan out concurrently.
    Returns a dict keyed by uppercase symbol: {price, open, time}.
    Silently skips failed tickers; returns {} if BRAPI_TOKEN is absent.
    """
    token = os.environ.get("BRAPI_TOKEN", "").strip()
    if not token or not full_tickers:
        return {}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(sym: str) -> tuple[str, dict | None]:
        try:
            r = _requests.get(
                _BRAPI_QUOTE_URL + sym,
                params={"token": token},
                timeout=10,
            )
            r.raise_for_status()
            for item in r.json().get("results") or []:
                price = item.get("regularMarketPrice")
                open_ = item.get("regularMarketOpen")
                time_ = item.get("regularMarketTime")
                if price is not None:
                    return sym.upper(), {
                        "price": float(price),
                        "open": float(open_) if open_ is not None else None,
                        "time": str(time_) if time_ else None,
                    }
        except Exception:
            pass
        return sym.upper(), None

    result: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(_BRAPI_WORKERS, len(full_tickers))) as ex:
        futs = {ex.submit(_fetch_one, s) for s in full_tickers}
        for fut in as_completed(futs):
            sym_key, val = fut.result()
            if val is not None:
                result[sym_key] = val
    return result


@app.get("/api/portfolio/stream")
async def stream_portfolio(tickers: str = "") -> StreamingResponse:
    """SSE stream of live prices for a list of tickers.

    Emits one ``prices`` event immediately, then every 5 seconds.
    Each event contains the latest close, open, and timestamp per ticker.
    """
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers is required")
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:30]

    async def gen():
        yield ": stream-open\n\n"
        loop = asyncio.get_running_loop()
        try:
            while True:
                def _fetch():
                    today = date.today()
                    # Build root → full ticker mapping from DB
                    companies = load_companies_from_db()
                    root_to_full = {
                        c["ticker_root"]: c["ticker"]
                        for c in companies
                        if c["ticker_root"] in ticker_list
                    }
                    full_tickers = [
                        root_to_full[r] for r in ticker_list if r in root_to_full
                    ]
                    brapi = _brapi_quotes(full_tickers)

                    items = []
                    with db.connect() as conn:
                        for root in ticker_list:
                            full = root_to_full.get(root)
                            live = brapi.get(full) if full else None
                            if live:
                                items.append({
                                    "tickerRoot": root,
                                    "currentClose": live["price"],
                                    "dayOpen": live["open"],
                                    "asOf": live["time"] or today.isoformat(),
                                })
                            else:
                                # Fallback: last cached OHLC bar
                                bars = fetch_ohlc_trailing(conn, root, today, days=1)
                                if bars:
                                    b = bars[-1]
                                    items.append({
                                        "tickerRoot": root,
                                        "currentClose": float(b["close"]),
                                        "dayOpen": float(b["open"]),
                                        "asOf": b["bar_date"].isoformat(),
                                    })
                                else:
                                    items.append({
                                        "tickerRoot": root,
                                        "currentClose": None,
                                        "dayOpen": None,
                                        "asOf": today.isoformat(),
                                    })
                    return items

                items = await loop.run_in_executor(None, _fetch)
                yield f"data: {json.dumps({'type': 'prices', 'items': items})}\n\n"
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": repr(e)}


# ---------- Admin endpoints ----------

_VALID_JUDGMENT_LABELS = {"positive", "neutral", "negative", "skip", "bad_match"}


@app.get("/api/admin/articles")
def admin_articles(
    date_iso: str = Query(alias="date"),
    ticker: str | None = None,
):
    """Articles for a given SP-day, joined with any existing judgment.

    Query params:
      date   YYYY-MM-DD (required)
      ticker optional ticker root filter
    """
    try:
        from datetime import date as _date
        day = _date.fromisoformat(date_iso)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")

    with db.connect() as conn:
        with conn.cursor() as cur:
            params: list[Any] = [day]
            ticker_clause = ""
            if ticker:
                ticker_clause = "AND %s = ANY(a.matched_tickers)"
                params.append(ticker)
            cur.execute(
                f"""
                SELECT
                    a.url,
                    a.title,
                    a.site,
                    a.published_at,
                    a.sentiment,
                    a.sentiment_score,
                    a.matched_tickers,
                    j.label       AS judgment_label,
                    j.notes       AS judgment_notes
                FROM articles a
                LEFT JOIN LATERAL (
                    SELECT label, notes
                    FROM judgments
                    WHERE article_url = a.url
                    ORDER BY created_at DESC
                    LIMIT 1
                ) j ON true
                WHERE (a.published_at AT TIME ZONE 'America/Sao_Paulo')::date = %s
                {ticker_clause}
                ORDER BY a.published_at DESC
                """,
                params,
            )
            rows = cur.fetchall()

    return [
        {
            "url": r["url"],
            "title": r["title"],
            "site": r["site"],
            "publishedAt": r["published_at"].isoformat() if r["published_at"] else None,
            "sentiment": r["sentiment"],
            "sentimentScore": float(r["sentiment_score"]) if r["sentiment_score"] is not None else None,
            "matchedTickers": r["matched_tickers"] or [],
            "judgment": (
                {"label": r["judgment_label"], "notes": r["judgment_notes"] or ""}
                if r["judgment_label"] else None
            ),
        }
        for r in rows
    ]


class JudgmentBody(BaseModel):
    articleUrl: str
    label: str
    notes: str = ""


@app.post("/api/admin/judgments")
def admin_upsert_judgment(body: JudgmentBody):
    """Insert a judgment for an article. Multiple judgments per article are
    kept (audit trail); GET /admin/articles returns the most recent one."""
    if body.label not in _VALID_JUDGMENT_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"label must be one of {sorted(_VALID_JUDGMENT_LABELS)}",
        )
    judge = os.environ.get("JUDGE_NAME") or "admin"
    with db.connect() as conn:
        db.insert_judgment(
            conn,
            article_url=body.articleUrl,
            judge=judge,
            label=body.label,
            notes=body.notes or None,
        )
        conn.commit()
    return {"ok": True}
