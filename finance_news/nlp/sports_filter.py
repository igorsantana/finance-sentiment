"""High-precision detector for sports / sponsorship articles.

Pure function, no model loads — safe to import from both ``extract`` (forward)
and the backfill script. The pipeline calls ``detect_sports_context`` after
ticker matching and empties ``matched_tickers`` when the verdict is positive
(see ``finance_news/extract.py``), so a Superliga Gerdau write-up doesn't end
up attached to GGBR's day summary.

Heuristic (precision-first):

    sports_score  = 5*title_sport_hits + body_sport_hits
    finance_score = 4*title_finance_hits + body_finance_hits
                    + 2*ticker_regex_hits
    is_sports = sports_score >= 6  AND  finance_score <= 2

A real finance article that mentions a sponsorship in passing (`"Gerdau
patrocina Superliga e investe R$500mi em capex"`) hits enough finance terms
to keep ``is_sports`` False; pure sports coverage rarely contains tickers,
balanço vocabulary, or B3 references and crosses the threshold.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

BODY_WINDOW = 1500          # chars; matches rank_subjects' lead bias
PER_TERM_CAP = 3            # cap each term's contribution
SPORTS_THRESHOLD = 6
FINANCE_CEILING = 2

_SPORTS_TERMS = (
    "superliga", "brasileirao", "libertadores", "copa do brasil",
    "champions", "mundial de clubes", "volei", "voleibol", "futebol",
    "basquete", "tenis", "formula 1", "automobilismo", "surfe",
    "mma", "ufc", "partida", "placar", "rodada", "campeonato",
    "semifinal", "atleta", "jogador", "jogadora", "torcida", "arbitro",
)

_FINANCE_TERMS = (
    "receita", "lucro", "ebitda", "dividendo", "acao", "acoes",
    "bovespa", "ibovespa", "balanco", "trimestre", "cvm", "oferta",
    "ipo", "aquisicao", "fusao", "endividamento", "capex", "analista",
    "corretora", "papel", "papeis",
)

_TICKER_RE = re.compile(r"\b[A-Z]{4}\d{1,2}\b")


@dataclass(frozen=True)
class SportsVerdict:
    is_sports: bool
    reasons: list[str]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def _count_hits(haystack: str, needles: tuple[str, ...]) -> tuple[int, list[str]]:
    """Capped hit count + ordered list of distinct matched terms."""
    total = 0
    matched: list[str] = []
    for term in needles:
        hits = haystack.count(term)
        if hits == 0:
            continue
        total += min(hits, PER_TERM_CAP)
        matched.append(term)
    return total, matched


def detect_sports_context(
    title: str,
    text: str,
    subjects: list[str] | None = None,
    companies_ner: list[str] | None = None,  # noqa: ARG001 — reserved for later refinements
) -> SportsVerdict:
    """Decide whether ``(title, text)`` is sports/sponsorship coverage."""
    title_norm = _norm(title or "")
    body_norm = _norm((text or "")[:BODY_WINDOW])

    title_sport, title_sport_terms = _count_hits(title_norm, _SPORTS_TERMS)
    body_sport, body_sport_terms = _count_hits(body_norm, _SPORTS_TERMS)
    title_fin, _ = _count_hits(title_norm, _FINANCE_TERMS)
    body_fin, _ = _count_hits(body_norm, _FINANCE_TERMS)

    # Tickers are uppercase by spec, so search the original text, not the
    # normalized lower-cased copy.
    ticker_hits = len(_TICKER_RE.findall((title or "") + "\n" + (text or "")[:BODY_WINDOW]))

    sports_score = 5 * title_sport + body_sport
    finance_score = 4 * title_fin + body_fin + 2 * ticker_hits

    # Subject-level sports tag is a soft boost: a single sport keyword in the
    # title plus matching subject is enough to clear the bar.
    if subjects:
        subj_norm = " ".join(_norm(s) for s in subjects)
        for term in _SPORTS_TERMS:
            if term in subj_norm:
                sports_score += 2
                title_sport_terms.append(f"subj:{term}")
                break

    is_sports = sports_score >= SPORTS_THRESHOLD and finance_score <= FINANCE_CEILING

    reasons: list[str] = []
    for t in title_sport_terms[:3]:
        reasons.append(f"title:{t}")
    for t in body_sport_terms[:3]:
        reasons.append(f"body:{t}")

    return SportsVerdict(is_sports=is_sports, reasons=reasons[:5])
