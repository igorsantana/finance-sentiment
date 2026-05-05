# scripts/

Utility and maintenance scripts for the Finance News project.

| Folder / File | Purpose |
|---|---|
| `migrate.py` | Idempotent DB migration runner — applies new files from `migrations/` lexically |
| `cron_loop.py` | Runs the pipeline on a schedule (used by Docker cron service) |
| `backfill/` | One-shot scripts to reprocess existing DB rows without re-ingesting |
| `companies/` | Fetch and update company metadata from external sources |
| `diagnostics/` | Audit and probe tools for investigating data quality |
| `judging/` | CLI and stats helpers for evaluating NLP extraction quality |
