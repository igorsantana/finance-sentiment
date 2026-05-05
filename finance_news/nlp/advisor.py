"""LLM "investment advisor" narratives over a rolling 3/7/14-day window.

Two flavors:
- ``summarize_market_window``  — market-wide read for the Mercado tab.
- ``summarize_company_window`` — focused on one ticker for the Empresa tab.

Both return ``{"paragraphs": [str, str], "model": str}`` (exactly two
paragraphs) or ``None`` on connection / parse / empty errors. The HTTP
caller maps ``None`` to a 503 so the FE can show the soft-fail tile.

Reuses the same env-driven OpenAI-compatible client wiring as
``finance_news.nlp.llm_summary``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("advisor")

_TIMEOUT_SECONDS = 120
_PARAGRAPH_CHAR_CAP = 600

_SYSTEM_PROMPT = (
    "Você é um assessor de investimentos brasileiro experiente. Recebe um "
    "resumo agregado dos últimos dias de cobertura jornalística do mercado "
    "(ou de uma empresa) e produz uma análise sóbria em português. "
    "Responda EXCLUSIVAMENTE com JSON válido no formato "
    '{"paragraphs": ["...", "..."]}, contendo EXATAMENTE dois parágrafos. '
    "Cada parágrafo tem no máximo 4 frases. NÃO dê recomendações diretas "
    "de compra/venda — use linguagem cautelosa como \"atenção a\", "
    "\"monitorar\", \"vale acompanhar\". Não invente fatos que não estejam "
    "nos dados fornecidos."
)


def _client():
    from openai import OpenAI
    base_url = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    api_key = os.environ.get("LLM_API_KEY") or "ollama"
    return OpenAI(base_url=base_url, api_key=api_key, timeout=_TIMEOUT_SECONDS)


def _call(user_prompt: str, model: str) -> Optional[dict[str, Any]]:
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
    except Exception as e:  # noqa: BLE001 — soft-fail surface
        log.warning("advisor LLM call failed: %s", e)
        return None

    raw = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not raw:
        log.warning("advisor: empty LLM response")
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("advisor: non-JSON response: %s; raw=%r", e, raw[:200])
        return None

    paragraphs = [
        p.strip()[:_PARAGRAPH_CHAR_CAP]
        for p in (parsed.get("paragraphs") or [])
        if isinstance(p, str) and p.strip()
    ]
    if len(paragraphs) < 2:
        log.warning("advisor: expected 2 paragraphs, got %d", len(paragraphs))
        return None

    return {"paragraphs": paragraphs[:2], "model": model}


def _format_daily(daily: list[dict[str, Any]]) -> str:
    lines = []
    for d in daily:
        net = d.get("net", 0.0)
        lines.append(
            f"- {d['date']}: total={d.get('total', 0)} "
            f"+{d.get('positive', 0)}/={d.get('neutral', 0)}/-{d.get('negative', 0)} "
            f"net={net:+.2f}"
        )
    return "\n".join(lines)


def _format_top_companies(items: list[dict[str, Any]], k: int = 8) -> str:
    return "\n".join(
        f"- {x['name']}: total={x['total']} tilt={x.get('tilt', 0):+.2f}"
        for x in items[:k]
    )


def _format_sectors(items: list[dict[str, Any]], k: int = 8) -> str:
    return "\n".join(
        f"- {x['sector']}: tilt={x.get('tilt', 0):+.2f} "
        f"(+{x['positive']}/={x['neutral']}/-{x['negative']})"
        for x in items[:k]
    )


def summarize_market_window(
    *,
    window_days: int,
    end: str,
    daily: list[dict[str, Any]],
    top_companies: list[dict[str, Any]],
    sector_matrix: list[dict[str, Any]],
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Market-wide narrative for the Mercado tab."""
    model = model or os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    user_prompt = (
        f"Janela: últimos {window_days} dias até {end}.\n\n"
        f"Volume e sentimento por dia:\n{_format_daily(daily)}\n\n"
        f"Empresas mais cobertas (com tilt = (pos-neg)/total):\n"
        f"{_format_top_companies(top_companies)}\n\n"
        f"Setores ordenados por tilt:\n{_format_sectors(sector_matrix)}\n\n"
        "Produza o JSON com dois parágrafos: (1) leitura do mercado "
        "(tendência de sentimento, setores que lideram e que ficam para "
        "trás); (2) observações acionáveis sobre o que monitorar nos "
        "próximos pregões."
    )
    return _call(user_prompt, model)


def summarize_company_window(
    *,
    ticker: str,
    name: str,
    window_days: int,
    end: str,
    daily: list[dict[str, Any]],
    correlation: Optional[float],
    top_subjects: list[dict[str, Any]],
    top_publishers: list[dict[str, Any]],
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Per-company narrative for the Empresa tab in window mode."""
    model = model or os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    closes = [d for d in daily if d.get("close") is not None]
    price_lines = "\n".join(
        f"- {d['date']}: close={d['close']:.2f} net={d.get('net', 0):+.2f} "
        f"total={d.get('total', 0)}"
        for d in closes
    ) or "- (sem cotação no período)"
    subj = ", ".join(f"{x['subject']} ({x['count']})" for x in top_subjects[:8]) or "—"
    pubs = ", ".join(f"{x['site']} ({x['count']})" for x in top_publishers[:6]) or "—"
    corr_str = f"{correlation:+.2f}" if correlation is not None else "n/d"

    user_prompt = (
        f"Empresa: {name} (ticker {ticker}).\n"
        f"Janela: últimos {window_days} dias até {end}.\n\n"
        f"Cotação e sentimento por dia útil:\n{price_lines}\n\n"
        f"Correlação Pearson(close, net) no período: {corr_str}.\n"
        f"Assuntos mais frequentes: {subj}.\n"
        f"Veículos: {pubs}.\n\n"
        "Produza o JSON com dois parágrafos: (1) momentum + relação entre "
        "sentimento e preço no período; (2) o que vale acompanhar nas "
        "próximas sessões com base nos assuntos surgindo."
    )
    return _call(user_prompt, model)
