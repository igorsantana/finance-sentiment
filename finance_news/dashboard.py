"""Render an offline PNG dashboard summarizing today's news CSV.

Panels:
  1. Header — title, date, article + source counts, sentiment mix big numbers.
  2. Sentiment donut.
  3. Top companies by mention count, bars colored by net sentiment score.
  4. Top countries mentioned (horizontal bar).
  5. Sentiment breakdown per publisher (stacked horizontal bar).
  6. Currencies mentioned (horizontal bar).
  7. Callouts — most-positive / most-negative headlines of the day.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")  # force non-GUI backend (offline PNG render)
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.gridspec import GridSpec

log = logging.getLogger("dashboard")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

SP_TZ = ZoneInfo("America/Sao_Paulo")

COLORS = {
    "positive": "#2E8B57",   # sea green
    "neutral":  "#8A8F99",   # cool gray
    "negative": "#C0392B",   # brick red
    "accent":   "#1F4E79",   # deep blue (header)
    "bg":       "#F6F7FB",
}

SENTIMENT_ORDER = ["positive", "neutral", "negative"]


def _parse_pipe(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split("|") if x.strip()]


def _load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _net_sentiment(rows: list[dict]) -> float:
    """Return (pos - neg) / total in [-1, 1]."""
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

    # Sentiment mix big numbers (right side)
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
                ha="center", va="center", transform=ax.transAxes,
                color="#888")
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
    """Prefer `matched_companies` (curated top-150). Fall back to raw NER
    `companies` only if no rows carry matches (old CSV format)."""
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
                ha="center", va="center", transform=ax.transAxes,
                color="#888")
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
    ax.set_title(f"{title_prefix} — {len(top)}",
                 fontsize=13, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("menções", fontsize=10, color="#555")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)

    # Annotate count at bar end
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
                ha="center", va="center", transform=ax.transAxes,
                color="#888")
        ax.axis("off")
        return

    top = counts.most_common(top_n)
    names = [n for n, _ in top][::-1]
    values = [v for _, v in top][::-1]

    ax.barh(names, values, color=COLORS["accent"], edgecolor="white")
    ax.set_title(f"Top {len(top)} países mencionados",
                 fontsize=13, pad=10,
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


def _panel_sentiment_by_site(ax, rows: list[dict]) -> None:
    # Per-site sentiment counts, sorted by net sentiment (pos - neg).
    per_site: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if not r["site"] or not r["sentiment"]:
            continue
        per_site[r["site"]][r["sentiment"]] += 1

    if not per_site:
        ax.text(0.5, 0.5, "sem dados por veículo",
                ha="center", va="center", transform=ax.transAxes,
                color="#888")
        ax.axis("off")
        return

    sites = sorted(
        per_site.keys(),
        key=lambda s: (
            (per_site[s]["positive"] - per_site[s]["negative"])
            / max(sum(per_site[s].values()), 1)
        ),
    )
    pos = [per_site[s]["positive"] for s in sites]
    neu = [per_site[s]["neutral"] for s in sites]
    neg = [per_site[s]["negative"] for s in sites]

    ax.barh(sites, pos, color=COLORS["positive"], label="Positivo", edgecolor="white")
    ax.barh(sites, neu, left=pos, color=COLORS["neutral"], label="Neutro", edgecolor="white")
    ax.barh(sites, neg, left=[p + n for p, n in zip(pos, neu)],
            color=COLORS["negative"], label="Negativo", edgecolor="white")
    ax.set_title("Sentimento por veículo", fontsize=13, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("artigos", fontsize=10, color="#555")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", frameon=False, fontsize=9)


def _panel_sector_sentiment(ax, rows: list[dict], top_n: int = 10) -> None:
    """Stacked bar of positive/neutral/negative counts per BrAPI sector."""
    per_sector: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        sectors = _parse_pipe(r.get("sectors") or "")
        sent = r.get("sentiment", "")
        if not sectors or not sent:
            continue
        for s in sectors:
            per_sector[s][sent] += 1

    if not per_sector:
        ax.text(0.5, 0.5, "sem dados de setor",
                ha="center", va="center", transform=ax.transAxes,
                color="#888")
        ax.axis("off")
        return

    # Sort by net sentiment tilt so the most positive sector is at top.
    items = sorted(
        per_sector.items(),
        key=lambda kv: (
            (kv[1]["positive"] - kv[1]["negative"])
            / max(sum(kv[1].values()), 1)
        ),
    )[-top_n:]

    sectors = [s for s, _ in items]
    pos = [c["positive"] for _, c in items]
    neu = [c["neutral"] for _, c in items]
    neg = [c["negative"] for _, c in items]

    ax.barh(sectors, pos, color=COLORS["positive"], label="Positivo",
            edgecolor="white")
    ax.barh(sectors, neu, left=pos, color=COLORS["neutral"], label="Neutro",
            edgecolor="white")
    ax.barh(sectors, neg, left=[p + n for p, n in zip(pos, neu)],
            color=COLORS["negative"], label="Negativo", edgecolor="white")
    ax.set_title("Sentimento por setor", fontsize=13, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("artigos", fontsize=10, color="#555")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", frameon=False, fontsize=9)


def _panel_currencies(ax, rows: list[dict], top_n: int = 8) -> None:
    counts: Counter = Counter()
    for r in rows:
        for c in _parse_pipe(r["currencies"]):
            counts[c] += 1

    if not counts:
        ax.text(0.5, 0.5, "sem moedas detectadas",
                ha="center", va="center", transform=ax.transAxes,
                color="#888")
        ax.axis("off")
        return

    top = counts.most_common(top_n)
    names = [n for n, _ in top][::-1]
    values = [v for _, v in top][::-1]
    ax.barh(names, values, color="#6A5ACD", edgecolor="white")
    ax.set_title("Moedas mencionadas", fontsize=13, pad=10,
                 color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("menções", fontsize=10, color="#555")
    ax.tick_params(axis="both", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    for i, v in enumerate(values):
        ax.text(v + max(values) * 0.01, i, str(v),
                va="center", fontsize=8, color="#333")


def _panel_headline_callouts(ax, rows: list[dict]) -> None:
    """Show the most confident positive + negative headlines."""
    ax.axis("off")

    def best(sentiment: str, k: int = 3) -> list[tuple[str, str, float]]:
        subset = [
            (
                r["title"][:95],
                r["site"],
                float(r["sentiment_score"] or 0.0),
            )
            for r in rows
            if r.get("sentiment") == sentiment and r.get("title")
        ]
        subset.sort(key=lambda x: x[2], reverse=True)
        return subset[:k]

    y = 0.92
    ax.text(0.01, y, "Destaques do dia", fontsize=13, fontweight="bold",
            color=COLORS["accent"], transform=ax.transAxes)
    y -= 0.10

    for label, sentiment in (("Positivos", "positive"), ("Negativos", "negative")):
        ax.text(
            0.01, y, label, fontsize=11, fontweight="bold",
            color=COLORS[sentiment], transform=ax.transAxes,
        )
        y -= 0.07
        items = best(sentiment)
        if not items:
            ax.text(0.03, y, "— sem artigos nessa categoria hoje —",
                    fontsize=9, color="#888", transform=ax.transAxes,
                    style="italic")
            y -= 0.08
            continue
        for title, site, score in items:
            ax.text(0.03, y, f"• {title}", fontsize=9.5,
                    color="#222", transform=ax.transAxes)
            y -= 0.05
            ax.text(0.05, y, f"{site}  ·  confiança {score:.2f}",
                    fontsize=8.5, color="#888", transform=ax.transAxes)
            y -= 0.06
        y -= 0.02


def render(rows: list[dict], target_date: date, out_path: Path) -> Path:
    sns.set_theme(style="white")
    fig = plt.figure(figsize=(16, 14), facecolor=COLORS["bg"])
    gs = GridSpec(
        nrows=4, ncols=2, figure=fig,
        height_ratios=[0.9, 3.0, 3.0, 2.6],
        hspace=0.55, wspace=0.22,
        left=0.06, right=0.97, top=0.96, bottom=0.04,
    )

    ax_header = fig.add_subplot(gs[0, :])
    ax_donut = fig.add_subplot(gs[1, 0])
    ax_companies = fig.add_subplot(gs[1, 1])
    ax_countries = fig.add_subplot(gs[2, 0])
    ax_sites = fig.add_subplot(gs[2, 1])
    ax_sectors = fig.add_subplot(gs[3, 0])
    ax_callouts = fig.add_subplot(gs[3, 1])

    for ax in (
        ax_donut, ax_companies, ax_countries,
        ax_sites, ax_sectors, ax_callouts,
    ):
        ax.set_facecolor(COLORS["bg"])

    _panel_header(ax_header, rows, target_date)
    _panel_sentiment_donut(ax_donut, rows)
    _panel_top_companies(ax_companies, rows)
    _panel_top_countries(ax_countries, rows)
    _panel_sentiment_by_site(ax_sites, rows)
    _panel_sector_sentiment(ax_sectors, rows)
    _panel_headline_callouts(ax_callouts, rows)

    fig.savefig(out_path, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument(
        "--date",
        help="ISO date (YYYY-MM-DD). Default: today in America/Sao_Paulo.",
    )
    p.add_argument("--in", dest="in_path", type=Path,
                   help="Input CSV. Default: data/news_<date>.csv")
    p.add_argument("--out", type=Path,
                   help="Output PNG. Default: data/dashboard_<date>.png")
    args = p.parse_args(argv)

    day = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(SP_TZ).date()
    )
    in_path = args.in_path or DATA_DIR / f"news_{day.isoformat()}.csv"
    out_path = args.out or DATA_DIR / f"dashboard_{day.isoformat()}.png"

    if not in_path.exists():
        log.error("Input CSV missing: %s — run the extract stage first.", in_path)
        return 2

    rows = _load_rows(in_path)
    if not rows:
        log.error("%s has no rows.", in_path)
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    render(rows, day, out_path)
    log.info("Wrote %s (%d articles, net sentiment %+.2f)",
             out_path, len(rows), _net_sentiment(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
