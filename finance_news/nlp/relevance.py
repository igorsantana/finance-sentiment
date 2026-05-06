"""Embedding-based company relevance scorer.

Uses ``paraphrase-multilingual-MiniLM-L12-v2`` (384-dim, PT-BR capable,
~118 MB) to filter alias matches that are semantically unrelated to the
matched company — e.g. a "vale tudo" TV article matched via the VALE alias.

Ticker-path matches are intentionally bypassed (a ticker code like VALE3 in a
real article is unambiguous); only alias-path candidates are filtered.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from finance_news.nlp.companies import Company

log = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RELEVANCE_THRESHOLD = 0.30
_ARTICLE_LEAD_CHARS = 400


def _profile(company: "Company") -> str:
    from finance_news.nlp.companies import translate_sector
    sector_pt = translate_sector(company.sector) if company.sector else ""
    base = company.short_name or company.ticker_root
    if sector_pt:
        return (
            f"{base} é uma empresa brasileira do setor de {sector_pt}, "
            f"listada na B3 ({company.ticker})"
        )
    return f"{base} é uma empresa brasileira listada na B3 ({company.ticker})"


class CompanyRelevanceScorer:
    """Lazy-loaded sentence-embedding scorer for alias-match filtering."""

    def __init__(self, companies: list["Company"]) -> None:
        self._companies = companies
        self._tokenizer = None
        self._model = None
        self._load_failed = False
        # Populated by _load(): root → profile embedding row index
        self._root_to_idx: dict[str, int] = {}
        self._profile_matrix: np.ndarray | None = None  # shape (N, 384)

    def _load(self) -> None:
        if self._model is not None or self._load_failed:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer

            t0 = time.monotonic()
            self._tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            self._model = AutoModel.from_pretrained(MODEL_NAME)
            self._model.eval()

            profiles = [_profile(c) for c in self._companies]
            self._profile_matrix = self._encode(profiles)
            self._root_to_idx = {
                c.ticker_root: i for i, c in enumerate(self._companies)
            }
            log.info(
                "Loaded relevance model %s in %.1fs; %d company profiles encoded",
                MODEL_NAME, time.monotonic() - t0, len(profiles),
            )
            del torch  # keep import local to avoid top-level torch dep
        except Exception as exc:
            log.error("Failed to load relevance model: %s", exc)
            self._load_failed = True

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Tokenise → forward pass → mean-pool → L2-normalise. Shape (N, 384)."""
        import torch

        enc = self._tokenizer(
            texts, padding=True, truncation=True, max_length=128,
            return_tensors="pt",
        )
        with torch.no_grad():
            out = self._model(**enc)
        # Mean-pool over non-padding tokens
        mask = enc["attention_mask"].unsqueeze(-1).float()
        pooled = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        arr = pooled.cpu().numpy().astype(np.float32)
        # L2-normalise each row
        norms = np.linalg.norm(arr, axis=1, keepdims=True).clip(min=1e-9)
        return arr / norms

    def embed_article(self, title: str, text: str) -> np.ndarray | None:
        """Encode the article lead (title + first 400 chars of body).

        Returns shape ``(384,)`` float32, or ``None`` if the model failed to
        load (soft-fail — caller should treat as no filtering).
        """
        self._load()
        if self._model is None:
            return None
        lead = (title or "") + ". " + (text or "")[:_ARTICLE_LEAD_CHARS]
        return self._encode([lead])[0]

    def filter_matches(
        self,
        article_embedding: np.ndarray | None,
        companies: list["Company"],
    ) -> list["Company"]:
        """Keep only companies whose profile cosine-similarity ≥ threshold.

        If ``article_embedding`` is ``None`` (model failed) or the profile
        matrix is unavailable, all companies pass through unchanged.
        """
        if (
            article_embedding is None
            or self._profile_matrix is None
            or not companies
        ):
            return companies

        keep: list["Company"] = []
        for c in companies:
            idx = self._root_to_idx.get(c.ticker_root)
            if idx is None:
                keep.append(c)
                continue
            sim = float(np.dot(article_embedding, self._profile_matrix[idx]))
            if sim >= RELEVANCE_THRESHOLD:
                keep.append(c)
            else:
                log.debug(
                    "Relevance filter: dropped %s (sim=%.3f < %.2f)",
                    c.ticker_root, sim, RELEVANCE_THRESHOLD,
                )
        return keep
