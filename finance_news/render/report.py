"""Render the daily company + sector report PNG from the ``articles`` table.

``render(rows, target_date) -> bytes`` is pure (no disk I/O); the CLI shim
writes ``data/images/<date>/report.png``.
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib.gridspec import GridSpec

from finance_news.nlp.companies import translate_sector as _pt_sector
from finance_news.render.dashboard import load_rows  # shared row-loader

log = logging.getLogger("report")

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
SENT_PT = {"positive": "Positivo", "neutral": "Neutro", "negative": "Negativo"}


def _parse_pipe(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split("|") if x.strip()]


def _tilt(pos: int, neg: int, total: int) -> float:
    return (pos - neg) / max(total, 1)


def build_company_df(rows: list[dict]) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    articles: dict[str, list[dict]] = defaultdict(list)
    use_matched = any(r.get("matched_companies") for r in rows)
    field = "matched_companies" if use_matched else "companies"
    for r in rows:
        companies = _parse_pipe(r.get(field) or "")
        sent = r.get("sentiment", "")
        if not companies or not sent:
            continue
        for c in companies:
            counts[c][sent] += 1
            articles[c].append(r)
    return {"counts": counts, "articles": articles}


def build_sector_df(rows: list[dict]) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    companies: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        sectors = _parse_pipe(r.get("sectors") or "")
        co_names = _parse_pipe(r.get("matched_companies") or r.get("companies") or "")
        sent = r.get("sentiment", "")
        if not sectors or not sent:
            continue
        for s in sectors:
            counts[s][sent] += 1
            for c in co_names:
                companies[s][c] += 1
    return {"counts": counts, "companies": companies}


def _panel_header(ax, rows: list[dict], target_date: date) -> None:
    ax.axis("off")
    ax.set_facecolor(COLORS["bg"])
    matched = [r for r in rows if r.get("matched_companies")]
    companies_set = {c for r in matched for c in _parse_pipe(r.get("matched_companies") or "")}
    sectors_set = {s for r in matched for s in _parse_pipe(r.get("sectors") or "")}
    total = len(matched) or 1
    pos = sum(1 for r in matched if r.get("sentiment") == "positive")
    neg = sum(1 for r in matched if r.get("sentiment") == "negative")
    net = (pos - neg) / total
    net_label = f"{net:+.0%}"

    ax.text(
        0.01, 0.88,
        f"Sentimento por Empresa e Setor — {target_date.isoformat()}",
        fontsize=22, fontweight="bold", color=COLORS["accent"],
        transform=ax.transAxes, va="top",
    )
    stats = [
        (len(matched), "artigos com empresa"),
        (len(companies_set), "empresas citadas"),
        (len(sectors_set), "setores cobertos"),
        (net_label, "saldo líquido"),
    ]
    tilt_color = (
        COLORS["positive"] if net > 0
        else (COLORS["negative"] if net < 0 else COLORS["neutral"])
    )
    stat_colors = ["#333", "#333", "#333", tilt_color]
    for i, ((val, label), color) in enumerate(zip(stats, stat_colors)):
        x = 0.125 + i * 0.25
        ax.text(x, 0.38, str(val), fontsize=26, fontweight="bold",
                color=color, ha="center", va="center", transform=ax.transAxes)
        ax.text(x, 0.08, label, fontsize=10, color="#666",
                ha="center", va="center", transform=ax.transAxes)


def _panel_company_bars(ax, company_data: dict, top_n: int = 20) -> None:
    counts = company_data["counts"]
    if not counts:
        ax.text(0.5, 0.5, "sem empresas detectadas",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        return
    totals = {c: sum(v.values()) for c, v in counts.items()}
    top = sorted(
        totals,
        key=lambda c: (
            totals[c],
            _tilt(counts[c]["positive"], counts[c]["negative"], totals[c]),
        ),
        reverse=True,
    )[:top_n]
    top.reverse()
    pos_vals = [counts[c]["positive"] for c in top]
    neu_vals = [counts[c]["neutral"]  for c in top]
    neg_vals = [counts[c]["negative"] for c in top]
    ax.barh(top, pos_vals, color=COLORS["positive"], label="Positivo", edgecolor="white")
    ax.barh(top, neu_vals, left=pos_vals, color=COLORS["neutral"], label="Neutro", edgecolor="white")
    left_neg = [p + n for p, n in zip(pos_vals, neu_vals)]
    ax.barh(top, neg_vals, left=left_neg, color=COLORS["negative"], label="Negativo", edgecolor="white")
    ax.set_title(f"Sentimento por empresa (maiores {len(top)})",
                 fontsize=13, pad=12, color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("artigos", fontsize=10, color="#555")
    ax.tick_params(axis="y", labelsize=8)
    ax.tick_params(axis="x", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    max_total = max(totals[c] for c in top) or 1
    for i, c in enumerate(top):
        total = totals[c]
        ax.text(total + max_total * 0.01, i, str(total),
                va="center", fontsize=7.5, color="#444")


def _panel_sector_heatmap(ax, sector_data: dict) -> None:
    counts = sector_data["counts"]
    if not counts:
        ax.text(0.5, 0.5, "sem dados de setor",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        return
    sentiments = SENTIMENT_ORDER
    sectors = sorted(
        counts.keys(),
        key=lambda s: _tilt(counts[s]["positive"], counts[s]["negative"], sum(counts[s].values())),
        reverse=True,
    )
    count_matrix = np.array(
        [[counts[s][sent] for sent in sentiments] for s in sectors],
        dtype=int,
    )
    color_matrix = np.zeros_like(count_matrix, dtype=float)
    color_matrix[:, 0] = count_matrix[:, 0]
    color_matrix[:, 1] = 0
    color_matrix[:, 2] = -count_matrix[:, 2]
    vabs = max(abs(color_matrix).max(), 1)
    im = ax.imshow(color_matrix, cmap="RdYlGn", aspect="auto",
                   vmin=-vabs, vmax=vabs)
    ax.set_xticks(range(len(sentiments)))
    ax.set_xticklabels([SENT_PT[s] for s in sentiments], fontsize=10)
    ax.set_yticks(range(len(sectors)))
    ax.set_yticklabels([_pt_sector(s) for s in sectors], fontsize=8)
    for i, s in enumerate(sectors):
        for j, sent in enumerate(sentiments):
            n = count_matrix[i, j]
            text_color = "white" if abs(color_matrix[i, j]) > vabs * 0.5 else "#333"
            ax.text(j, i, str(n), ha="center", va="center",
                    fontsize=8.5, color=text_color, fontweight="bold")
    ax.set_title("Mapa de calor de sentimento por setor",
                 fontsize=13, pad=12, color=COLORS["accent"], fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.7, label="saldo líquido (pos − neg)", pad=0.02)


def _panel_sector_drilldown(ax, sector_data: dict) -> None:
    counts = sector_data["counts"]
    top_companies = sector_data["companies"]
    if not counts:
        ax.text(0.5, 0.5, "sem dados de setor",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        ax.axis("off")
        return
    items = sorted(
        counts.items(),
        key=lambda kv: _tilt(kv[1]["positive"], kv[1]["negative"], sum(kv[1].values())),
    )
    sectors = [s for s, _ in items]
    sector_labels = [_pt_sector(s) for s in sectors]
    pos = [c["positive"] for _, c in items]
    neu = [c["neutral"]  for _, c in items]
    neg = [c["negative"] for _, c in items]
    ax.barh(sector_labels, pos, color=COLORS["positive"], label="Positivo", edgecolor="white")
    ax.barh(sector_labels, neu, left=pos, color=COLORS["neutral"], label="Neutro", edgecolor="white")
    ax.barh(sector_labels, neg, left=[p + n for p, n in zip(pos, neu)],
            color=COLORS["negative"], label="Negativo", edgecolor="white")
    for i, sector in enumerate(sectors):
        top2 = [c for c, _ in top_companies[sector].most_common(2)]
        if top2:
            label = ", ".join(top2)
            total = sum(counts[sector].values())
            ax.text(total + 0.1, i, label, va="center",
                    fontsize=7, color="#555", style="italic")
    ax.set_title("Classificação de setores com empresas principais",
                 fontsize=13, pad=12, color=COLORS["accent"], fontweight="bold")
    ax.set_xlabel("artigos", fontsize=10, color="#555")
    ax.tick_params(axis="y", labelsize=9)
    ax.tick_params(axis="x", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", frameon=False, fontsize=9)


def _panel_headline_callouts(ax, rows: list[dict], company_data: dict, top_n: int = 5) -> None:
    ax.axis("off")
    ax.set_facecolor(COLORS["bg"])
    counts = company_data["counts"]
    articles = company_data["articles"]
    if not counts:
        ax.text(0.5, 0.5, "sem empresas com artigos",
                ha="center", va="center", transform=ax.transAxes, color="#888")
        return
    totals = {c: sum(v.values()) for c, v in counts.items()}
    top_companies = sorted(totals, key=lambda c: totals[c], reverse=True)[:top_n]
    ax.text(0.01, 0.97, "Destaques das empresas mais citadas",
            fontsize=13, fontweight="bold", color=COLORS["accent"],
            transform=ax.transAxes)
    y = 0.90
    dy_company = 0.055
    dy_headline = 0.045
    dy_meta = 0.038
    for company in top_companies:
        if y < 0.05:
            break
        art = articles[company]
        ax.text(0.01, y, f"▸ {company}  ({totals[company]} artigos)",
                fontsize=10, fontweight="bold", color=COLORS["accent"],
                transform=ax.transAxes)
        y -= dy_company
        for sentiment, color_key in (("positive", "positive"), ("negative", "negative")):
            subset = sorted(
                [r for r in art if r.get("sentiment") == sentiment and r.get("title")],
                key=lambda r: float(r.get("sentiment_score") or 0),
                reverse=True,
            )
            if not subset and sentiment == "positive":
                subset = sorted(
                    [r for r in art if r.get("title")],
                    key=lambda r: float(r.get("sentiment_score") or 0),
                    reverse=True,
                )[:1]
            if not subset:
                continue
            r = subset[0]
            title = (r["title"] or "")[:90]
            site = r.get("site", "")
            score = float(r.get("sentiment_score") or 0)
            if y < 0.05:
                break
            ax.text(0.03, y, f"• {title}", fontsize=8.5,
                    color=COLORS[color_key], transform=ax.transAxes)
            y -= dy_headline
            ax.text(0.05, y, f"{site}  ·  confiança {score:.2f}",
                    fontsize=7.5, color="#888", transform=ax.transAxes)
            y -= dy_meta
        y -= 0.015


def render(rows: list[dict], target_date: date) -> bytes:
    sns.set_theme(style="white")
    fig = plt.figure(figsize=(20, 24), facecolor=COLORS["bg"])
    gs = GridSpec(
        nrows=3, ncols=2, figure=fig,
        height_ratios=[1.4, 6, 6],
        hspace=0.60, wspace=0.18,
        left=0.07, right=0.96, top=0.96, bottom=0.04,
    )
    ax_header    = fig.add_subplot(gs[0, :])
    ax_companies = fig.add_subplot(gs[1, 0])
    ax_heatmap   = fig.add_subplot(gs[1, 1])
    ax_drilldown = fig.add_subplot(gs[2, 0])
    ax_callouts  = fig.add_subplot(gs[2, 1])
    for ax in (ax_companies, ax_heatmap, ax_drilldown, ax_callouts):
        ax.set_facecolor(COLORS["bg"])

    company_data = build_company_df(rows)
    sector_data  = build_sector_df(rows)

    _panel_header(ax_header, rows, target_date)
    _panel_company_bars(ax_companies, company_data)
    _panel_sector_heatmap(ax_heatmap, sector_data)
    _panel_sector_drilldown(ax_drilldown, sector_data)
    _panel_headline_callouts(ax_callouts, rows, company_data)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Render company+sector sentiment report PNG.")
    p.add_argument("--date", help="ISO date (YYYY-MM-DD). Default: today in America/Sao_Paulo.")
    p.add_argument("--out", dest="out_path", type=Path,
                   help="Output PNG. Default: data/images/<date>/report.png")
    args = p.parse_args(argv)

    day = date.fromisoformat(args.date) if args.date else datetime.now(SP_TZ).date()
    out_path = args.out_path or DATA_DIR / "images" / day.isoformat() / "report.png"

    rows = load_rows(day)
    if not rows:
        log.warning("No articles for %s — skipping report.", day.isoformat())
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(render(rows, day))
    log.info("Wrote %s (%d articles)", out_path, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
