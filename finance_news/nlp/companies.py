"""Companies: DB loader, sector translation, and the alias matcher used by
``finance_news.extract`` to map free-text article bodies to ticker roots.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from finance_news.store import db

log = logging.getLogger(__name__)


@dataclass
class Company:
    ticker: str        # e.g. PETR4
    ticker_root: str   # e.g. PETR
    short_name: str    # e.g. Petrobras
    long_name: str     # e.g. Petróleo Brasileiro S.A.
    sector: str        # e.g. Energy Minerals
    market_cap: int


SECTOR_PT = {
    "Commercial Services":    "Serviços Comerciais",
    "Communications":         "Comunicações",
    "Consumer Durables":      "Bens de Consumo Duráveis",
    "Consumer Non-Durables":  "Bens de Consumo Não Duráveis",
    "Consumer Services":      "Serviços ao Consumidor",
    "Distribution Services":  "Serviços de Distribuição",
    "Electronic Technology":  "Tecnologia Eletrônica",
    "Energy Minerals":        "Petróleo e Gás",
    "Finance":                "Financeiro",
    "Health Services":        "Serviços de Saúde",
    "Health Technology":      "Tecnologia em Saúde",
    "Industrial Services":    "Serviços Industriais",
    "Miscellaneous":          "Diversos",
    "Non-Energy Minerals":    "Mineração",
    "Process Industries":     "Indústria de Processos",
    "Producer Manufacturing": "Bens de Capital",
    "Retail Trade":           "Varejo",
    "Technology Services":    "Serviços de Tecnologia",
    "Transportation":         "Transporte",
    "Utilities":              "Utilidade Pública",
}


def translate_sector(name: str) -> str:
    return SECTOR_PT.get(name, name)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def load_companies_from_db() -> list[dict[str, Any]]:
    """Return all rows from the ``companies`` table, sorted by market cap desc."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker_root, ticker, short_name, long_name,
                   sector, market_cap
            FROM companies
            ORDER BY market_cap DESC NULLS LAST
            """
        )
        return cur.fetchall()


def to_company(row: dict[str, Any]) -> Company:
    """Adapt a raw ``companies`` table row into a ``Company`` dataclass."""
    return Company(
        ticker=(row["ticker"] or "").strip().upper(),
        ticker_root=(row["ticker_root"] or "").strip().upper(),
        short_name=(row.get("short_name") or "").strip(),
        long_name=(row.get("long_name") or "").strip(),
        sector=(row.get("sector") or "").strip(),
        market_cap=int(row.get("market_cap") or 0),
    )


# Tokens that would create catastrophic false-positives if matched as aliases
# (too common, too short, or collide with ordinary Portuguese words).
_ALIAS_STOPLIST = {
    "sa", "s/a", "brasil", "holding", "holdings", "participacoes",
    "cia", "companhia", "grupo", "ltda",
    "pn", "on", "unit",
    "off",
}
_MIN_ALIAS_LEN = 3


# Normalized aliases that collide with everyday PT-BR words or proper nouns
# (cities, given names). Hits on these are graded by ``_alias_context_score``
# against the surrounding window before being accepted.
_AMBIGUOUS_ALIASES = {
    "vale",         # verb valer / noun vale (coupon, valley)
    "rumo",         # noun rumo (direction)
    "movida",       # adjective/participle movida ("movida a etanol")
    "americanas",   # adjective "empresas americanas", "latinas americanas"
    "tim",          # common given name (Tim, Timóteo)
    "equatorial",   # adjective ("zona equatorial", "Guiné Equatorial")
    "minerva",      # mythological name, also generic surname
    "anima",        # archaic noun "ânima" (soul)
    "suzano",       # also a city in São Paulo (Suzano-SP)
    "natura", "localiza", "raia", "vibra", "ultra", "cielo", "cogna",
    "porto seguro",
}

# Window-level cues for the context gate. Normalized form: lowercase,
# accent-stripped, punctuation preserved. Lists are precision-first — a real
# finance article almost always carries at least one of these tokens within
# 200 chars of the company alias.
_FINANCE_CONTEXT = (
    "s.a.", "acao", "acoes", "empresa", "companhia", "cotacao", "cotacoes",
    "bovespa", "b3", "ibovespa", "cvm", "balanco", "trimestre", "lucro",
    "prejuizo", "receita", "ebitda", "papel", "papeis", "investidor",
    "investidores", "acionista", "acionistas", "ipo", "dividendo",
    "dividendos", "guidance", "fato relevante", "ri ",
)
_PLACE_CONTEXT = (
    "cidade", "municipio", "prefeitura", "prefeito", "bairro",
    "rua ", "avenida ", "regiao metropolitana", "morador", "moradores",
    "interior de", "zona norte", "zona sul", "zona leste", "zona oeste",
    "estado de sao paulo",
)
_CONTEXT_WINDOW = 200       # chars on each side of the alias match
_CONTEXT_THRESHOLD = 1      # min score to accept an ambiguous match


def _alias_context_score(
    *,
    text: str,
    normalized: str,
    match_start: int,
    match_end: int,
    alias: str,
    ticker_re: Optional[re.Pattern],
    org_texts: set[str],
) -> int:
    """Grade an ambiguous alias hit against its surrounding context.

    Strong evidence (ticker code anywhere in the article, or alias inside a
    spaCy ORG span) tips the score positive on its own; window-level
    finance/place vocabulary refines borderline cases (e.g., a Suzano
    article that mentions the city but no business signals).
    """
    score = 0
    if ticker_re is not None and ticker_re.search(text):
        score += 4
    if any(alias in o for o in org_texts):
        score += 3
    lo = max(0, match_start - _CONTEXT_WINDOW)
    hi = min(len(normalized), match_end + _CONTEXT_WINDOW)
    window = normalized[lo:hi]
    score += sum(1 for term in _FINANCE_CONTEXT if term in window)
    score -= 2 * sum(1 for term in _PLACE_CONTEXT if term in window)
    return score


def _norm_org_set(doc) -> set[str]:
    """Collect normalized text of spaCy ORG entities from a doc."""
    if doc is None:
        return set()
    out: set[str] = set()
    for ent in getattr(doc, "ents", ()):
        if ent.label_ == "ORG":
            key = _norm(ent.text)
            if key:
                out.add(key)
    return out


class CompanyMatcher:
    """Regex-backed matcher that maps article text → {short_name, ticker_root}.

    Two independent matching paths run on every article:

    1. **Name aliases** (short_name, long_name) — matched case-insensitively
       against accent-stripped text, gated by ``_AMBIGUOUS_ALIASES``.
    2. **Tickers** (e.g. PETR4, QUAL3, VALE) — matched case-sensitively on
       the original text. Ticker codes are always uppercase in PT-BR finance
       journalism, so this avoids collisions with lowercase Portuguese words.
    """

    def __init__(self, companies: list[Company]):
        self.companies = companies
        self._alias_to_root: dict[str, str] = {}
        self._root_to_company: dict[str, Company] = {}
        self._ticker_re_by_root: dict[str, re.Pattern] = {}
        patterns: list[str] = []
        for c in companies:
            self._root_to_company[c.ticker_root] = c
            if c.ticker_root:
                tickers = {c.ticker, c.ticker_root}
                alternation = "|".join(
                    sorted(
                        (re.escape(t) for t in tickers if t),
                        key=len, reverse=True,
                    )
                )
                # Case-sensitive: tickers are always uppercase in real articles.
                # Accept bare root (VALE) or root + class digits (VALE3, VALE11).
                self._ticker_re_by_root[c.ticker_root] = re.compile(
                    rf"\b(?:{alternation})\d{{0,2}}\b"
                )
            for alias in self._aliases_for(c):
                key = _norm(alias)
                if not key or len(key) < _MIN_ALIAS_LEN:
                    continue
                if key in _ALIAS_STOPLIST:
                    continue
                self._alias_to_root[key] = c.ticker_root
                patterns.append(re.escape(key))
        if patterns:
            # Longest-first so "banco do brasil" wins over "brasil".
            patterns.sort(key=len, reverse=True)
            self._regex = re.compile(
                r"(?<![a-z0-9])(" + "|".join(patterns) + r")(?![a-z0-9])",
                re.IGNORECASE,
            )
        else:
            self._regex = None

    @staticmethod
    def _aliases_for(c: Company) -> list[str]:
        aliases = []
        if c.short_name:
            aliases.append(c.short_name)
        if c.long_name and c.long_name.lower() != (c.short_name or "").lower():
            aliases.append(c.long_name)
        return aliases

    def match(
        self,
        text: str,
        doc=None,
        *,
        org_texts: Optional[set[str]] = None,
        relevance_scorer=None,
        title: str = "",
    ) -> tuple[list[Company], Optional["np.ndarray"]]:
        """Return ``(companies, article_embedding)``.

        ``article_embedding`` is the 384-dim relevance embedding when
        ``relevance_scorer`` is provided, otherwise ``None``.
        Ticker-path matches bypass relevance filtering (ticker codes are
        unambiguous in real articles); only alias-path candidates are scored.
        """
        if not text:
            return [], None
        if org_texts is None:
            org_texts = _norm_org_set(doc)
        alias_roots: list[str] = []
        ticker_roots: list[str] = []
        seen: set[str] = set()

        # Path 1: name aliases over normalized text.
        if self._regex is not None:
            normalized = _norm(text)
            for m in self._regex.finditer(normalized):
                alias = m.group(1)
                root = self._alias_to_root.get(alias)
                if not root or root in seen:
                    continue
                if alias in _AMBIGUOUS_ALIASES:
                    score = _alias_context_score(
                        text=text,
                        normalized=normalized,
                        match_start=m.start(1),
                        match_end=m.end(1),
                        alias=alias,
                        ticker_re=self._ticker_re_by_root.get(root),
                        org_texts=org_texts,
                    )
                    if score < _CONTEXT_THRESHOLD:
                        continue
                seen.add(root)
                alias_roots.append(root)

        # Path 2: case-sensitive ticker scan. Uppercase-only by construction,
        # so it can't collide with Portuguese prose.
        for root, ticker_re in self._ticker_re_by_root.items():
            if root in seen:
                continue
            if ticker_re.search(text):
                seen.add(root)
                ticker_roots.append(root)

        article_emb = None
        if relevance_scorer is not None and alias_roots:
            article_emb = relevance_scorer.embed_article(title, text)
            alias_companies = [self._root_to_company[r] for r in alias_roots]
            alias_companies = relevance_scorer.filter_matches(article_emb, alias_companies)
            alias_roots = [c.ticker_root for c in alias_companies]

        found_roots = alias_roots + ticker_roots
        return [self._root_to_company[r] for r in found_roots], article_emb

    def sector_of(self, ticker_root: str) -> Optional[str]:
        c = self._root_to_company.get(ticker_root.upper())
        return c.sector if c else None
