#!/usr/bin/env bash
# Restore the demo to its seed state: fresh deals + approvals log, no quotes.
# Safe to run between takes; touches only data/*.csv and quotes/*.md.
set -euo pipefail
cd "$(dirname "$0")/.."

cp data/seed/deals.csv data/deals.csv
cp data/seed/approvals_log.csv data/approvals_log.csv
find quotes -maxdepth 1 -name '*.md' -delete
rm -f data/*.tmp

# HubSpot mode: put the 15 demo deals back to their seed values in the CRM too.
if grep -qs '^DESK_BACKEND=hubspot' .env; then
  python3 scripts/crm_hubspot.py seed
fi

echo "Deal desk reset: $(($(wc -l < data/deals.csv) - 1)) deals, $(($(wc -l < data/approvals_log.csv) - 1)) log entries, 0 quotes."
python3 scripts/deskctl.py pending
