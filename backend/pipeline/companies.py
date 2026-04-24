"""Load companies.csv and match articles against the top-150 alias dictionary."""
from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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


def load_companies(path: Path) -> list[Company]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out: list[Company] = []
    for r in rows:
        try:
            out.append(Company(
                ticker=r["ticker"].strip().upper(),
                ticker_root=r["ticker_root"].strip().upper(),
                short_name=(r["short_name"] or "").strip(),
                long_name=(r["long_name"] or "").strip(),
                sector=(r.get("sector") or "").strip(),
                market_cap=int(float(r.get("market_cap") or 0)),
            ))
        except (KeyError, ValueError) as e:
            log.debug("skipping malformed row: %r (%s)", r, e)
    return out


# Tokens that would create catastrophic false-positives if matched as aliases
# (too common, too short, or collide with ordinary Portuguese words).
_ALIAS_STOPLIST = {
    "sa", "s/a", "brasil", "holding", "holdings", "participacoes",
    "cia", "companhia", "grupo", "ltda",
    "pn", "on", "unit",
    # one- or two-letter ticker roots would match randomly
    "on", "off",
}
_MIN_ALIAS_LEN = 3

# Normalized aliases that collide with everyday PT-BR words. When the matcher
# sees one of these, it requires contextual evidence (ticker in text, or the
# alias falling inside a spaCy ORG span) before accepting the match.
_AMBIGUOUS_ALIASES = {
    "vale",         # verb valer / noun vale (coupon, valley)
    "rumo",         # noun rumo (direction)
    "movida",       # adjective/participle movida ("movida a etanol")
    "americanas",   # adjective "empresas americanas", "latinas americanas"
    "tim",          # common given name (Tim, Timóteo)
    "equatorial",   # adjective ("zona equatorial", "Guiné Equatorial")
    "minerva",      # mythological name, also generic surname
    "anima",        # archaic noun "ânima" (soul)
    # kept defensively in case the companies.csv schema surfaces these
    # as standalone aliases in the future (currently they appear only
    # inside multi-word short_names like "NATURA COSMETICOS").
    "natura", "localiza", "raia", "vibra", "ultra", "cielo", "cogna",
}


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
       journalism, so this avoids catastrophic collisions with lowercase
       Portuguese words (e.g. ``qual`` the pronoun vs. ``QUAL`` the Qualicorp
       ticker root).
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
                    sorted((re.escape(t) for t in tickers if t), key=len, reverse=True)
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
        """Name-only aliases. Tickers are handled separately via the
        case-sensitive ``_ticker_re_by_root`` scan to avoid lowercase
        PT-word collisions (e.g. ``qual`` ~ QUAL)."""
        aliases = []
        if c.short_name:
            aliases.append(c.short_name)
        if c.long_name and c.long_name.lower() != (c.short_name or "").lower():
            aliases.append(c.long_name)
        return aliases

    def match(self, text: str, doc=None) -> list[Company]:
        """Return the companies whose aliases or tickers appear in ``text``.

        Name aliases (short_name / long_name) are matched case-insensitively
        on accent-stripped text. For ambiguous aliases (see
        ``_AMBIGUOUS_ALIASES``) a match is only accepted when there is
        contextual evidence:
          - the company's ticker or ticker_root appears (case-sensitively)
            elsewhere in the original text, or
          - the alias falls inside a spaCy ORG entity span in ``doc``.

        Tickers (PETR4, VALE, QUAL3) are matched separately on the original
        text, case-sensitively — this catches market-report articles that
        reference codes without the full brand name.
        """
        if not text:
            return []
        org_texts = _norm_org_set(doc)
        found_roots: list[str] = []
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
                    ticker_re = self._ticker_re_by_root.get(root)
                    has_ticker = bool(ticker_re and ticker_re.search(text))
                    in_org = any(alias in o for o in org_texts)
                    if not (has_ticker or in_org):
                        continue
                seen.add(root)
                found_roots.append(root)

        # Path 2: case-sensitive ticker scan. Uppercase-only by construction,
        # so it can't collide with Portuguese prose.
        for root, ticker_re in self._ticker_re_by_root.items():
            if root in seen:
                continue
            if ticker_re.search(text):
                seen.add(root)
                found_roots.append(root)

        return [self._root_to_company[r] for r in found_roots]

    def sector_of(self, ticker_root: str) -> Optional[str]:
        c = self._root_to_company.get(ticker_root.upper())
        return c.sector if c else None
