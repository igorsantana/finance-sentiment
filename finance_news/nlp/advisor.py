"""LLM "investment advisor" narratives over a rolling 3/7/14-day window.

Two flavors:
- ``summarize_market_window``  — market-wide read for the Mercado tab.
- ``summarize_company_window`` — focused on one ticker for the Empresa tab.

Both return ``{"paragraphs": [str, str, str], "model": str}`` (exactly
three paragraphs) or ``None`` on connection / parse / empty errors. The
HTTP caller maps ``None`` to a 503 so the FE can show the soft-fail tile.

Voice
-----
The model plays the role of a Brazilian investment advisor speaking to a
busy investor who knows the basics but doesn't have time to read the
news themselves. The output must be plain-Portuguese narrative:

* No greetings or theatrical framing (no meeting metaphors); open with
  substance.
* No technical jargon from the data layer (``net``, ``tilt``,
  ``correlação de Pearson``, ``Z-score``, etc.).
* No buy/sell recommendations — use cautious framing like "vale
  acompanhar", "atenção a", "monitorar".
* No markdown, no bullet lists, no headings. Three short paragraphs of
  flowing prose, that's it.

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
_PARAGRAPH_CHAR_CAP = 700
_PARAGRAPHS_REQUIRED = 3

_SYSTEM_PROMPT = (
    "Você é um assessor de investimentos brasileiro experiente que resume "
    "o cenário para um investidor que entende o básico do mercado, mas não "
    "teve tempo de acompanhar as notícias. Tom direto, sóbrio e profissional — "
    "estilo briefing por escrito, não conversa ao vivo.\n"
    "\n"
    "Regras de redação (obrigatórias):\n"
    "1. Escreva em português do Brasil, em prosa fluida. NUNCA use listas, "
    "marcadores, títulos ou markdown — apenas parágrafos de texto corrido.\n"
    "2. SEM saudações, despedidas ou encenação de conversa: não use "
    "'Olá', 'Bom dia', 'Vamos lá', 'Começando', 'Peço licença', nem "
    "metáforas de reunião ou call ('abrimos a reunião', 'para começar', "
    "'antes de encerrar'). O primeiro parágrafo já entra no fundo — fatos "
    "e leitura do cenário.\n"
    "3. NÃO use jargão técnico vindo dos dados internos (não cite as "
    "palavras 'net', 'tilt', 'score', 'correlação de Pearson', 'viés' "
    "como número, nem percentuais crus tipo '0.42'). Traduza tudo isso "
    "para linguagem cotidiana ('predominância de notícias positivas', "
    "'movimento alinhado com o noticiário', 'clima mais cauteloso').\n"
    "4. NÃO dê recomendações diretas de compra ou venda. Use linguagem "
    "prudente: 'vale acompanhar', 'merece atenção', 'pode pressionar'.\n"
    "5. Não invente fatos, números ou eventos que não estejam nos dados "
    "fornecidos. Se um dado faltar, omita em vez de especular.\n"
    "6. NUNCA cite quantidades de notícias, artigos ou menções (ex.: "
    "'47 notícias', '12 matérias', 'alto volume de cobertura' em números). "
    "O leitor quer leitura de mercado — temas, empresas, sentimento e "
    "implicações — não estatísticas de volume.\n"
    "7. Cada parágrafo tem entre 3 e 5 frases. Mantenha frases curtas e "
    "claras — quem lê tem pressa.\n"
    "\n"
    "Saída: responda EXCLUSIVAMENTE com JSON válido no formato "
    '{"paragraphs": ["...", "...", "..."]} contendo EXATAMENTE três '
    "parágrafos, na ordem e com o conteúdo pedidos pelo usuário."
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
    if len(paragraphs) < _PARAGRAPHS_REQUIRED:
        log.warning(
            "advisor: expected %d paragraphs, got %d",
            _PARAGRAPHS_REQUIRED, len(paragraphs),
        )
        return None

    return {"paragraphs": paragraphs[:_PARAGRAPHS_REQUIRED], "model": model}


# ---------- descriptive translators ----------
#
# These map the raw ratios coming out of aggregations.py (-1.0 .. +1.0)
# to plain-Portuguese labels the LLM can fold straight into prose. The
# goal is that the prompt never contains a number it doesn't want the
# model to repeat back to the user.

def _describe_tilt(tilt: float) -> str:
    """Map a -1..+1 sentiment tilt to a phrase a human would say."""
    if tilt >= 0.4:
        return "amplamente positivas"
    if tilt >= 0.15:
        return "predominantemente positivas"
    if tilt > -0.15:
        return "equilibradas entre positivas e negativas"
    if tilt > -0.4:
        return "predominantemente negativas"
    return "amplamente negativas"


def _describe_correlation(corr: Optional[float]) -> str:
    """Map a -1..+1 Pearson correlation to a price-vs-sentiment phrase."""
    if corr is None:
        return "sem alinhamento mensurável entre preço e clima das notícias no período"
    a = abs(corr)
    if a < 0.2:
        return "preço praticamente independente do clima das notícias"
    if a < 0.5:
        if corr > 0:
            return "preço acompanhando moderadamente o clima das notícias"
        return "preço se movendo moderadamente no sentido contrário ao clima das notícias"
    if a < 0.8:
        if corr > 0:
            return "preço fortemente alinhado com o clima das notícias"
        return "preço fortemente contrário ao clima das notícias"
    if corr > 0:
        return "preço quase colado ao clima das notícias"
    return "preço quase espelhando o clima das notícias no sentido oposto"


def _describe_price_change(daily: list[dict[str, Any]]) -> Optional[str]:
    """First-to-last close move across the window, as a phrase."""
    closes = [d for d in daily if d.get("close") is not None]
    if len(closes) < 2:
        return None
    start = float(closes[0]["close"])
    end = float(closes[-1]["close"])
    if start == 0:
        return None
    pct = (end - start) / start * 100
    if pct >= 5:
        return f"alta acumulada de {pct:.1f}% no período"
    if pct >= 1.5:
        return f"alta moderada de {pct:.1f}%"
    if pct > -1.5:
        return f"variação pequena de {pct:+.1f}%"
    if pct > -5:
        return f"queda moderada de {abs(pct):.1f}%"
    return f"queda acumulada de {abs(pct):.1f}% no período"


# ---------- input formatters (LLM-facing) ----------

def _format_daily_market(daily: list[dict[str, Any]]) -> str:
    """Per-day qualitative sentiment for the market view (no article counts)."""
    lines = []
    for d in daily:
        total = d.get("total", 0)
        if total <= 0:
            lines.append(f"- {d['date']}: pouca ou nenhuma cobertura relevante")
            continue
        tilt = d.get("net", 0)
        lines.append(
            f"- {d['date']}: tom do noticiário {_describe_tilt(tilt)}"
        )
    return "\n".join(lines) or "- (sem cobertura no período)"


def _format_top_companies(items: list[dict[str, Any]], k: int = 8) -> str:
    return "\n".join(
        f"- {x['name']}: noticiário {_describe_tilt(x.get('tilt', 0))} no período"
        for x in items[:k]
    ) or "- (sem empresas em destaque)"


def _format_sectors(items: list[dict[str, Any]], k: int = 8) -> str:
    return "\n".join(
        f"- {x['sector']}: clima {_describe_tilt(x.get('tilt', 0))} na cobertura do setor"
        for x in items[:k]
    ) or "- (sem setores destacados)"


def _format_daily_company(daily: list[dict[str, Any]]) -> str:
    """Per-day price + qualitative sentiment (no article counts)."""
    lines = []
    for d in daily:
        close = d.get("close")
        total = d.get("total", 0)
        if total > 0:
            sentiment_part = (
                f"noticiário {_describe_tilt(d.get('net', 0))}"
            )
        else:
            sentiment_part = "sem cobertura relevante na imprensa"
        if close is not None:
            lines.append(
                f"- {d['date']}: fechamento R$ {float(close):.2f}; {sentiment_part}"
            )
        else:
            lines.append(f"- {d['date']}: sem cotação; {sentiment_part}")
    return "\n".join(lines) or "- (sem dados no período)"


# ---------- public entry points ----------

def summarize_market_window(
    *,
    window_days: int,
    end: str,
    daily: list[dict[str, Any]],
    top_companies: list[dict[str, Any]],
    sector_matrix: list[dict[str, Any]],
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Market-wide narrative for the Mercado tab (3 paragraphs)."""
    model = model or os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

    user_prompt = (
        f"Janela de análise: últimos {window_days} dias úteis até {end}.\n"
        "\n"
        "Clima do noticiário, dia a dia (qualitativo):\n"
        f"{_format_daily_market(daily)}\n"
        "\n"
        "Empresas em destaque no período e o tom da cobertura sobre cada uma:\n"
        f"{_format_top_companies(top_companies)}\n"
        "\n"
        "Setores e o clima predominante na cobertura:\n"
        f"{_format_sectors(sector_matrix)}\n"
        "\n"
        "Escreva exatamente três parágrafos de análise (sem citar quantos "
        "artigos ou notícias existiram). Nesta ordem:\n"
        "1) Panorama geral do mercado na janela: narrativa dominante, ritmo "
        "da semana e o que o noticiário financeiro está sinalizando. "
        "Comece direto — sem saudação nem enquadre de reunião.\n"
        "2) Sentimento e leitura setorial/empresarial: quais nomes e setores "
        "aparecem com tom mais construtivo ou mais cauteloso, e o que isso "
        "sugere sobre o humor do investidor.\n"
        "3) Tendências e pontos de atenção para os próximos pregões: temas "
        "em evidência, riscos e catalisadores. Sem recomendações diretas "
        "de compra ou venda."
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
    model: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Per-company narrative for the Empresa tab (3 paragraphs)."""
    model = model or os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

    subj = ", ".join(f"{x['subject']}" for x in top_subjects[:6]) or "—"
    correlation_phrase = _describe_correlation(correlation)
    price_move = _describe_price_change(daily) or "movimento de preço pouco expressivo"

    user_prompt = (
        f"Empresa: {name} (ticker {ticker}).\n"
        f"Janela de análise: últimos {window_days} dias úteis até {end}.\n"
        "\n"
        "Cotação e clima das notícias, dia a dia:\n"
        f"{_format_daily_company(daily)}\n"
        "\n"
        f"Resumo do movimento da ação no período: {price_move}.\n"
        f"Relação observada entre preço e noticiário: {correlation_phrase}.\n"
        f"Assuntos mais frequentes na cobertura: {subj}.\n"
        "\n"
        "Escreva exatamente três parágrafos de análise (sem citar quantos "
        "artigos saíram). Nesta ordem:\n"
        "1) Panorama da empresa na janela: histórias e assuntos que dominam "
        "a cobertura (use os assuntos listados) e o que isso indica sobre "
        "o momento da companhia. Comece direto no assunto.\n"
        "2) Ação versus tom do noticiário: como o preço se comportou e se "
        "o mercado parece alinhado, contrário ou indiferente ao que a "
        "imprensa destacou — em prosa, sem jargão estatístico.\n"
        "3) Tendências e pontos de atenção: temas que podem ganhar peso, "
        "gatilhos e riscos. Sem recomendar compra ou venda."
    )
    return _call(user_prompt, model)
