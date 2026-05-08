"""CVM Dados Abertos — Fatos Relevantes and Comunicados ao Mercado.

Downloads the CVM IPE ZIP for the current year (updated periodically by the
regulator), filters to the target date's filings in the high-signal categories,
and returns (row, Candidate) pairs ready for article fetching via
fetch_article_direct().

No API key needed. No rate limits. Direct document URLs — no decode step required.

Column reference (actual CSV schema as of 2026):
  CNPJ_Companhia, Nome_Companhia, Codigo_CVM, Data_Referencia, Categoria,
  Tipo, Especie, Assunto, Data_Entrega, Tipo_Apresentacao, Protocolo_Entrega,
  Versao, Link_Download
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)


@dataclass
class Candidate:
    """Lightweight (url, title, published) tuple for CVM filings.

    Lives here — instead of in ``finance_news.net.discovery`` — because
    CVM is the only consumer. ``finance_news.net.discovery`` covers
    publisher listings and emits its own ``DiscoveredArticle`` shape;
    keeping the CVM tuple local avoids the two unrelated discovery
    surfaces sharing types.
    """
    url: str
    title: Optional[str]
    published: Optional[datetime]

CVM_ZIP_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/"
    "ipe_cia_aberta_{year}.zip"
)
CVM_ENCODING = "latin-1"
CVM_SEP = ";"

# Only these categories carry market-moving signal
CVM_CATEG_INCLUDE = {"Fato Relevante", "Comunicado ao Mercado"}


def fetch_cvm_csv(year: int) -> Optional[str]:
    """Download the CVM IPE ZIP for the given year and extract its CSV.

    Returns raw CSV text (latin-1 decoded) or None on failure.
    """
    url = CVM_ZIP_URL.format(year=year)
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            csv_name = next(
                (n for n in zf.namelist() if n.lower().endswith(".csv")), None
            )
            if csv_name is None:
                log.warning("CVM ZIP has no CSV entry: %s", url)
                return None
            return zf.read(csv_name).decode(CVM_ENCODING)
    except Exception as e:
        log.warning("CVM ZIP download/extract failed (%s): %s", url, e)
        return None


def is_pdf_link(link: str) -> bool:
    """Return True if Link_Download points to a PDF (trafilatura cannot extract these)."""
    lower = link.lower()
    path = urlparse(link).path.lower()
    return path.endswith(".pdf") or "tipo=pdf" in lower or ".pdf?" in lower


def cvm_candidates_for_date(
    target_date: date, year: int
) -> list[tuple[dict, Candidate]]:
    """Download CVM ZIP and return (raw_row, Candidate) pairs for target_date.

    Filters to rows where Data_Entrega == target_date and Categoria is in
    CVM_CATEG_INCLUDE. PDF links are skipped eagerly.
    """
    csv_text = fetch_cvm_csv(year)
    if not csv_text:
        return []

    target_str = target_date.strftime("%Y-%m-%d")
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=CVM_SEP)

    results: list[tuple[dict, Candidate]] = []
    for row in reader:
        if row.get("Data_Entrega", "").strip() != target_str:
            continue
        categ = row.get("Categoria", "").strip()
        if categ not in CVM_CATEG_INCLUDE:
            continue
        link = row.get("Link_Download", "").strip()
        if not link:
            continue
        if is_pdf_link(link):
            log.debug("CVM: skipping PDF %s", link)
            continue

        pub: Optional[datetime] = None
        try:
            pub = datetime.strptime(target_str, "%Y-%m-%d")
        except ValueError:
            pass

        # Tipo gives a human-readable label (e.g. "Fato Relevante")
        title = row.get("Tipo", "").strip() or categ
        # Append the Assunto (subject) to the title for more context
        assunto = row.get("Assunto", "").strip()
        if assunto:
            title = f"{title}: {assunto}"

        results.append((row, Candidate(url=link, title=title, published=pub)))

    log.info("CVM: %d filings for %s (year=%d)", len(results), target_date, year)
    return results
