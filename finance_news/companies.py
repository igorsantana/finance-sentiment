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
            log.warning("skipping malformed row: %r (%s)", r, e)
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


class CompanyMatcher:
    """Regex-backed matcher that maps article text → {short_name, ticker_root}.

    Aliases for each company:
      - short_name (quoted phrase, word-boundary)
      - long_name (same)
      - ticker (PETR4)
      - ticker_root (PETR)
    """

    def __init__(self, companies: list[Company]):
        self.companies = companies
        self._alias_to_root: dict[str, str] = {}
        self._root_to_company: dict[str, Company] = {}
        patterns: list[str] = []
        for c in companies:
            self._root_to_company[c.ticker_root] = c
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
        if c.ticker:
            aliases.append(c.ticker)
        if c.ticker_root and c.ticker_root != c.ticker:
            aliases.append(c.ticker_root)
        return aliases

    def match(self, text: str) -> list[Company]:
        if self._regex is None or not text:
            return []
        found_roots: list[str] = []
        seen: set[str] = set()
        for m in self._regex.finditer(_norm(text)):
            root = self._alias_to_root.get(m.group(1))
            if root and root not in seen:
                seen.add(root)
                found_roots.append(root)
        return [self._root_to_company[r] for r in found_roots]

    def sector_of(self, ticker_root: str) -> Optional[str]:
        c = self._root_to_company.get(ticker_root.upper())
        return c.sector if c else None
