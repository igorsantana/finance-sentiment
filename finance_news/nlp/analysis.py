"""Sentiment, subject ranking, and author/publisher conflict detection.

Sentiment: `turing-usp/FinBert-PTBR` — BERTimbau fine-tuned on PT-BR financial
news. We fall back to a multilingual Twitter/XLM-RoBERTa model if it fails to
download, because losing analysis for every article is worse than a less
domain-tuned score.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# --- Sentiment ---------------------------------------------------------------
# PT-BR financial-news model by Lucas Leme (BERTimbau fine-tuned). Three-class.
PRIMARY_MODEL = "lucas-leme/FinBERT-PT-BR"
FALLBACK_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"

# FinBert-PTBR outputs: POSITIVE / NEGATIVE / NEUTRAL (uppercase varies per model)
_LABEL_NORM = {
    "positive": "positive", "positivo": "positive", "pos": "positive",
    "label_2": "positive",
    "neutral": "neutral", "neutro": "neutral", "label_1": "neutral",
    "negative": "negative", "negativo": "negative", "neg": "negative",
    "label_0": "negative",
}


@dataclass
class SentimentResult:
    label: str       # positive | neutral | negative
    score: float     # confidence in [0, 1]


class SentimentAnalyzer:
    """Lazy-loaded HuggingFace pipeline with graceful fallback."""

    def __init__(self) -> None:
        self._pipe = None
        self._model_name: Optional[str] = None
        self._load_failed = False  # short-circuit after first failure

    def _load(self):
        if self._pipe is not None or self._load_failed:
            return
        from transformers import pipeline  # lazy: heavy import

        for model in (PRIMARY_MODEL, FALLBACK_MODEL):
            try:
                self._pipe = pipeline(
                    "sentiment-analysis",
                    model=model,
                    tokenizer=model,
                    truncation=True,
                    max_length=512,
                )
                self._model_name = model
                log.info("Loaded sentiment model: %s", model)
                return
            except Exception as e:
                log.warning("Failed to load %s: %s", model, e)
        self._load_failed = True
        raise RuntimeError(
            "No sentiment model could be loaded. Check network + HF cache."
        )

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    def predict(self, title: str, text: str) -> SentimentResult:
        """Score title + article lead. Finance headlines carry most of the tone;
        keeping the slice under ~1500 chars ensures we stay inside BERT's 512
        token window even after the tokenizer's worst-case split."""
        self._load()
        snippet = (title or "").strip() + ". " + (text or "").strip()
        snippet = snippet[:1500]
        out = self._pipe(snippet)[0]
        raw_label = str(out.get("label", "")).lower()
        label = _LABEL_NORM.get(raw_label, raw_label or "neutral")
        return SentimentResult(label=label, score=float(out.get("score", 0.0)))


# --- Subject identification --------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def rank_subjects(
    doc,
    title: str,
    companies: list[str],
    persons: list[str],
    top_k: int = 3,
) -> list[str]:
    """Return up to `top_k` primary subjects (companies + persons) ordered by
    salience. Scoring: title mention = 5, first 400 chars = 3, rest = 1, times
    a small log bonus for frequency."""
    import math

    title_norm = _norm(title or "")
    # spaCy doc text equals the analyzed text; first 400 chars is the lead.
    full_text = doc.text if doc is not None else ""
    lead = full_text[:400]
    lead_norm = _norm(lead)
    body_norm = _norm(full_text[400:])

    candidates: dict[str, tuple[str, float]] = {}
    for name in list(companies) + list(persons):
        key = _norm(name)
        if len(key) < 3:
            continue
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])")
        title_hits = len(pattern.findall(title_norm))
        lead_hits = len(pattern.findall(lead_norm))
        body_hits = len(pattern.findall(body_norm))
        total_hits = title_hits + lead_hits + body_hits
        if total_hits == 0:
            continue
        score = (
            5 * title_hits
            + 3 * lead_hits
            + 1 * body_hits
        ) * (1 + math.log1p(total_hits))
        prev = candidates.get(key)
        if prev is None or score > prev[1]:
            candidates[key] = (name, score)

    ranked = sorted(candidates.values(), key=lambda x: x[1], reverse=True)
    return [name for name, _ in ranked[:top_k]]


# --- Conflict detection ------------------------------------------------------
# Affiliations live in the `publishers.affiliations` column (seeded by
# migrations/002_seed_publishers.sql). To avoid one DB round-trip per article
# during extraction, the whole `publishers` table is loaded into a module
# cache on first call and walked in-process from there.
_publisher_cache: Optional[dict[str, dict]] = None


def _load_publisher_cache() -> dict[str, dict]:
    global _publisher_cache
    if _publisher_cache is None:
        from finance_news.store import db as _db
        with _db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT hostname, display_name, affiliations FROM publishers"
            )
            _publisher_cache = {r["hostname"]: r for r in cur.fetchall()}
    return _publisher_cache


def _resolve_publisher(hostname: str) -> Optional[dict]:
    if not hostname:
        return None
    cache = _load_publisher_cache()
    parts = hostname.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        row = cache.get(candidate)
        if row:
            return row
    return None


def detect_conflicts(
    hostname: str,
    author: Optional[str],
    subjects: list[str],
) -> list[str]:
    """Return a list of conflict flag strings. Empty means no conflict detected.

    Heuristics (all string-match, case/accent-insensitive):
      - publisher_subject: a subject entity belongs to the publisher's family.
      - author_self_reference: the author's name is also a subject entity.
    """
    flags: list[str] = []
    subj_norm = {_norm(s): s for s in subjects}

    # Publisher-subject overlap. Hostname → publishers row → affiliations.
    row = _resolve_publisher(hostname)
    related: list[str] = list(row.get("affiliations") or []) if row else []
    site = (row.get("display_name") if row else hostname) or hostname or ""
    for rel in related:
        key = _norm(rel)
        for subj_key, subj_display in subj_norm.items():
            if key == subj_key or key in subj_key or subj_key in key:
                flags.append(
                    f"publisher_subject:{subj_display} related to {site}"
                )
                break  # one flag per related-entity is enough

    # Author self-reference
    if author:
        a_norm = _norm(author)
        for subj_key, subj_display in subj_norm.items():
            if len(subj_key) < 4:
                continue
            if a_norm == subj_key or (
                " " in a_norm and a_norm in subj_key
            ) or (
                " " in subj_key and subj_key in a_norm
            ):
                flags.append(f"author_self_reference:{author} is a subject")
                break

    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out
