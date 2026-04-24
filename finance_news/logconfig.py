"""Quiet down noisy third-party loggers and deprecation warnings.

Imported for side effects by the pipeline entrypoints (ingest, extract, etc.)
so the console only shows our own INFO-level progress lines.
"""
from __future__ import annotations

import logging
import warnings


def silence_third_party() -> None:
    # urllib3 spams NotOpenSSLWarning on macOS LibreSSL; harmless.
    warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")
    try:
        from urllib3.exceptions import NotOpenSSLWarning
        warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
    except Exception:
        pass

    # FutureWarning / UserWarning from transformers + huggingface_hub are
    # never actionable at runtime.
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning, module="transformers")
    warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")

    for name in (
        "urllib3",
        "urllib3.connectionpool",
        "transformers",
        "transformers.tokenization_utils_base",
        "transformers.modeling_utils",
        "huggingface_hub",
        "filelock",
        "trafilatura",
        "trafilatura.core",
        "trafilatura.downloads",
        "trafilatura.utils",
        "trafilatura.htmlprocessing",
        "feedparser",
        "charset_normalizer",
    ):
        logging.getLogger(name).setLevel(logging.ERROR)


silence_third_party()
