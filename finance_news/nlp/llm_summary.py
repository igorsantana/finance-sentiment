"""LLM client for per-(company, day) good/bad-points summaries.

Talks to any OpenAI-compatible endpoint configured via env:
- ``LLM_BASE_URL`` — e.g. ``https://api.groq.com/openai/v1`` (default),
  ``https://openrouter.ai/api/v1``, ``http://ollama:11434/v1``.
- ``LLM_MODEL``   — e.g. ``deepseek-r1-distill-llama-70b``.
- ``LLM_API_KEY`` — required for hosted providers; ignored by Ollama
  (the placeholder ``"ollama"`` is sent when the var is empty so the
  SDK stays happy).

Soft-fails on connection or parsing errors so the rest of the pipeline
keeps moving.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("llm_summary")

_MAX_ARTICLES = 25
_SUMMARY_CHAR_CAP = 600
_TIMEOUT_SECONDS = 120

_SYSTEM_PROMPT = (
    "Você é um analista financeiro brasileiro. Recebe manchetes e resumos "
    "do dia sobre uma empresa listada na B3 e sintetiza o que o noticiário "
    "revela sobre ela — temas, fatos e tom — em português objetivo. "
    "Responda EXCLUSIVAMENTE com JSON válido no formato "
    '{"good": ["..."], "bad": ["..."]}, com 3 a 5 pontos em cada lista. "
    "Cada ponto é uma frase curta (até 25 palavras) de análise: o que "
    "aconteceu, o sentimento implícito e por que importa para o investidor. "
    "Não cite quantidade de matérias nem ordinal ('três notícias'). "
    "Não invente fatos ausentes nas fontes."
)


def _client():
    # Imported lazily so projects without `openai` installed (or with the
    # service offline) still load the module — the call site is the only
    # place that should bail.
    from openai import OpenAI

    base_url = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    api_key = os.environ.get("LLM_API_KEY") or "ollama"
    return OpenAI(base_url=base_url, api_key=api_key, timeout=_TIMEOUT_SECONDS)


def _format_articles(articles: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for a in articles[:_MAX_ARTICLES]:
        title = (a.get("title") or "").strip()
        summary = (a.get("summary") or "").strip()
        if len(summary) > _SUMMARY_CHAR_CAP:
            summary = summary[:_SUMMARY_CHAR_CAP].rsplit(" ", 1)[0] + "…"
        sentiment = a.get("sentiment") or "?"
        score = a.get("sentiment_score")
        score_str = f"{float(score):.2f}" if score is not None else "?"
        site = a.get("site") or ""
        meta = f"[tom: {sentiment}, score {score_str}] {site}".strip()
        lines.append(f"— {meta}\n  {title}\n  {summary}")
    return "\n\n".join(lines)


def summarize_company_day(
    name: str,
    ticker: str,
    articles: list[dict[str, Any]],
    *,
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Returns ``{"good": [...], "bad": [...], "model": "..."}`` or None on
    any failure (connection, bad JSON, empty arrays). Never raises."""
    if not articles:
        log.info("%s (%s): no articles, skipping summary", ticker, name)
        return None

    model = model or os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    user_prompt = (
        f"Empresa: {name} (ticker {ticker}).\n\n"
        "Material do dia (manchetes, veículo e tom de cada matéria):\n\n"
        f"{_format_articles(articles)}\n\n"
        "Sintetize em JSON good/bad: visão geral do dia para quem investe "
        "nessa ação — fatos, temas e leitura de sentimento, sem contar "
        "quantas notícias existiram."
    )

    try:
        client = _client()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except Exception as e:  # noqa: BLE001 — soft-fail surface
        log.warning("%s (%s): LLM call failed: %s", ticker, name, e)
        return None

    raw = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not raw:
        log.warning("%s (%s): empty LLM response", ticker, name)
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("%s (%s): LLM returned non-JSON: %s; raw=%r",
                    ticker, name, e, raw[:200])
        return None

    good = [s.strip() for s in (parsed.get("good") or []) if isinstance(s, str) and s.strip()]
    bad = [s.strip() for s in (parsed.get("bad") or []) if isinstance(s, str) and s.strip()]
    if not good and not bad:
        log.warning("%s (%s): LLM returned empty good/bad arrays", ticker, name)
        return None

    return {"good": good, "bad": bad, "model": model}
