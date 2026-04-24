#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Load .env if present
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

# Refresh companies.csv if missing or >7 days old (needs BRAPI_TOKEN).
COMPANIES=data/companies.csv
if [[ ! -f "$COMPANIES" ]] || [[ $(find "$COMPANIES" -mtime +7 -print 2>/dev/null) ]]; then
  if [[ -n "${BRAPI_TOKEN:-}" ]]; then
    echo "Refreshing companies.csv…"
    python backend/scripts/fetch_top_companies.py
  else
    echo "Warning: $COMPANIES missing/stale and BRAPI_TOKEN not set — skipping refresh." >&2
  fi
fi

python -m backend.pipeline.ingest "$@"
python -m backend.pipeline.extract
python -m backend.pipeline.dashboard
python -m backend.pipeline.report
