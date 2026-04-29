"""Render the daily PNG dashboard from the ``articles`` table.

``render(rows, target_date) -> bytes`` is pure (no disk I/O), so callers
embed it however they want. The CLI shim at the bottom is the only path that
writes to ``data/images/<date>/dashboard.png``.
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import matplotlib

matplotlib.use("Agg")  # force non-GUI backend (offline PNG render)
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.gridspec import GridSpec

from finance_news.store import db
from finance_news.nlp.companies import load_companies_from_db

log = logging.getLogger("dashboard")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SP_TZ = ZoneInfo("America/Sao_Paulo")

COLORS = {
    "positive": "#2E8B57",
    "neutral":  "#8A8F99",
    "negative": "#C0392B",
    "accent":   "#1F4E79",
    "bg":       "#F6F7FB",
}
SENTIMENT_ORDER = ["positive", "neutral", "negative"]


def _parse_pipe(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split("|") if x.strip()]


def load_rows(day: date) -> list[dict[str, Any]]:
    """Pull articles for ``day`` and shape them like the legacy CSV rows so the
    panel functions don't have to care about the storage format."""
    with db.connect() as conn:
        articles = db.fetch_articles_for_date(conn, day)
    company_map = {c["ticker_root"]: c for c in load_companies_from_db()}

    rows: list[dict[str, Any]] = []
    for a in articles:
        tickers = list(a.get("matched_tickers") or [])
        names = [
            company_map[t]["short_name"]
            for t in tickers
            if t in company_map and company_map[t].get("short_name")
        ]
        sectors = sorted({
            company_map[t]["sector"]
            for t in tickers
            if t in company_map and company_map[t].get("sector")
        })
        published = a.get("published_at")
        rows.append({
            "site": a.get("site") or "",
            "sentiment": a.get("sentiment") or "",
            "sentiment_score": (
                f"{a['sentiment_score']:.4f}" if a.get("sentiment_score") else ""
            ),
            "title": a.get("title") or "",
            "url": a.get("url") or "",
            "author": a.get("author") or "",
            "published_at": published.isoformat() if published else "",
            "subjects": "|".join(a.get("subjects") or []),
            "companies": "|".join(a.get("companies_ner") or []),
            "persons": "|".join(a.get("persons") or []),
            "countries": "|".join(a.get("countries") or []),
            "currencies": "|".join(a.get("currencies") or []),
            "matched_tickers": "|".join(tickers),
            "matched_companies": "|".join(names),
            "sectors": "|".join(sectors),
            "conflicts": "|".join(a.get("conflicts") or []),
            "summary": a.get("summary") or "",
        })
    return rows


def _net_sentiment(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    c = Counter(r["sentiment"] for r in rows)
    total = sum(c.values()) or 1
    return (c.get("positive", 0) - c.get("negative", 0)) / total


def _panel_header(ax, rows: list[dict], target_date: date) -> None:
    ax.axis("off")
    sites = len({r["site"] for r in rows if r["site"]})
    sent_counts = Counter(r["sentiment"] for r in rows if r["sentiment"])
    total = sum(sent_counts.values()) or 1

    ax.text(
        0.01, 0.78,
        f"Notícias Financeiras Brasileiras — {target_date.isoformat()}",
        fontsize=22, fontweight="bold", color=COLORS["accent"],
        transform=ax.transAxes,
    )
    ax.text(
        0.01, 0.45,
        f"{len(rows)} artigos · {sites} veículos",
        fontsize=13, color="#444", transform=ax.transAxes,
    )

    x_positions = [0.58, 0.72, 0.86]
    for x, sentiment in zip(x_positions, SENTIMENT_ORDER):
        n = sent_counts.get(sentiment, 0)
        pct = 100 * n / total
        ax.text(x, 0.72, f"{pct:.0f}%", fontsize=26, fontweight="bold",
                color=COLORS[sentiment], ha="center", transform=ax.transAxes)
        ax.text(x, 0.30, sentiment.capitalize(), fontsize=11,
                color="#555", ha="center", transform=ax.transAxes)
        ax.text(x, 0.12, f"{n} artigos", fontsize=9,
                color="#888", ha="center", transform=ax.transAxes)


def _panel_sentiment_donut(ax, rows: list[dict]) -> None:
    counts = Counter(r["sentiment"] for r in rows if r["sentiment"])
    labels = [s for s in SENTIMENT_ORDER if counts.get(s)]
    values = [counts[s] for s in labels]
    colors = [COLORS[s] for s in labels]

    if not values:
        ax.text(0.5, 0.5, "sem dados de sentimento",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        return

    wedges, _ = ax.pie(
        values, colors=colors, startangle=90, counterclock=False,
        wedgeprops={"width": 0.35, "edgecolor": "white", "linewidth": 2},
    )
    ax.set_title("Distribuição de sentimento", fontsize=13, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    total = sum(values)
    ax.text(0, 0, f"{total}\nartigos", ha="center", va="center",
            fontsize=14, fontweight="bold", color="#333")
    ax.legend(
        wedges,
        [f"{l.capitalize()} ({v})" for l, v in zip(labels, values)],
        loc="center", bbox_to_anchor=(0.5, -0.08), ncol=len(labels),
        frameon=False, fontsize=10,
    )


def _panel_top_companies(ax, rows: list[dict], top_n: int = 12) -> None:
    counts: Counter = Counter()
    sent_sum: dict[str, int] = defaultdict(int)
    use_matched = any(r.get("matched_companies") for r in rows)
    field = "matched_companies" if use_matched else "companies"
    for r in rows:
        names = _parse_pipe(r.get(field) or "")
        sent = r.get("sentiment", "")
        weight = {"positive": 1, "negative": -1}.get(sent, 0)
        for c in names:
            counts[c] += 1
            sent_sum[c] += weight

    if not counts:
        ax.text(0.5, 0.5, "sem empresas detectadas",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        return

    top = counts.most_common(top_n)
    names = [n for n, _ in top][::-1]
    values = [v for _, v in top][::-1]

    def color_for(name: str) -> str:
        net = sent_sum[name]
        if net > 0:
            return COLORS["positive"]
        if net < 0:
            return COLORS["negative"]
        return COLORS["neutral"]

    colors = [color_for(n) for n in names]
    ax.barh(names, values, color=colors, edgecolor="white")
    title_prefix = "Top empresas B3" if use_matched else "Top empresas (NER)"
    ax.set_title(f"{title_prefix} — {len(top)}", fontsize=13, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("menções", fontsize=10, color="#555")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    for i, v in enumerate(values):
        ax.text(v + max(values) * 0.01, i, str(v),
                va="center", fontsize=8, color="#333")


def _panel_top_countries(ax, rows: list[dict], top_n: int = 10) -> None:
    counts: Counter = Counter()
    for r in rows:
        for c in _parse_pipe(r["countries"]):
            counts[c] += 1
    if not counts:
        ax.text(0.5, 0.5, "sem países detectados",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        return
    top = counts.most_common(top_n)
    names = [n for n, _ in top][::-1]
    values = [v for _, v in top][::-1]
    ax.barh(names, values, color=COLORS["accent"], edgecolor="white")
    ax.set_title(f"Top {len(top)} países mencionados", fontsize=13, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("menções", fontsize=10, color="#555")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    for i, v in enumerate(values):
        ax.text(v + max(values) * 0.01, i, str(v),
                va="center", fontsize=8, color="#333")


def _panel_sentiment_by_site(ax, rows: list[dict], top_n: int = 25) -> None:
    per_site: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if not r["site"] or not r["sentiment"]:
            continue
        per_site[r["site"]][r["sentiment"]] += 1
    if not per_site:
        ax.text(0.5, 0.5, "sem dados por veículo",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        return
    ranked = sorted(per_site.items(),
                    key=lambda kv: sum(kv[1].values()), reverse=True)[:top_n]
    ranked.reverse()
    sites = [s for s, _ in ranked]
    pos = [c["positive"] for _, c in ranked]
    neu = [c["neutral"] for _, c in ranked]
    neg = [c["negative"] for _, c in ranked]
    ax.barh(sites, pos, color=COLORS["positive"], label="Positivo", edgecolor="white")
    ax.barh(sites, neu, left=pos, color=COLORS["neutral"], label="Neutro", edgecolor="white")
    ax.barh(sites, neg, left=[p + n for p, n in zip(pos, neu)],
            color=COLORS["negative"], label="Negativo", edgecolor="white")
    ax.set_title("Sentimento por veículo", fontsize=14, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("artigos", fontsize=11, color="#555")
    ax.tick_params(axis="y", labelsize=11)
    ax.tick_params(axis="x", labelsize=10)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", frameon=False, fontsize=10)


def render(rows: list[dict], target_date: date) -> bytes:
    sns.set_theme(style="white")
    fig = plt.figure(figsize=(16, 15), facecolor=COLORS["bg"])
    gs = GridSpec(
        nrows=3, ncols=2, figure=fig,
        height_ratios=[0.9, 3.0, 5.5],
        hspace=0.45, wspace=0.18,
        left=0.06, right=0.97, top=0.96, bottom=0.04,
    )
    ax_header    = fig.add_subplot(gs[0, :])
    ax_donut     = fig.add_subplot(gs[1, 0])
    ax_companies = fig.add_subplot(gs[1, 1])
    ax_countries = fig.add_subplot(gs[2, 0])
    ax_sites     = fig.add_subplot(gs[2, 1])
    for ax in (ax_donut, ax_companies, ax_countries, ax_sites):
        ax.set_facecolor(COLORS["bg"])

    _panel_header(ax_header, rows, target_date)
    _panel_sentiment_donut(ax_donut, rows)
    _panel_top_companies(ax_companies, rows)
    _panel_top_countries(ax_countries, rows)
    _panel_sentiment_by_site(ax_sites, rows)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="ISO date (YYYY-MM-DD). Default: today in America/Sao_Paulo.")
    p.add_argument("--out", type=Path, help="Output PNG. Default: data/images/<date>/dashboard.png")
    args = p.parse_args(argv)

    day = date.fromisoformat(args.date) if args.date else datetime.now(SP_TZ).date()
    out_path = args.out or DATA_DIR / "images" / day.isoformat() / "dashboard.png"

    rows = load_rows(day)
    if not rows:
        log.warning("No articles for %s — skipping dashboard.", day.isoformat())
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(render(rows, day))
    log.info("Wrote %s (%d articles, net sentiment %+.2f)",
             out_path, len(rows), _net_sentiment(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
