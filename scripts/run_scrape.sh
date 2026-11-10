#!/usr/bin/env bash
# Scraping semua kategori + gambar + sentimen. Dipanggil cron tiap jam.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="data/logs/scrape-$(date +%F).log"
find data/logs -name '*.log' -mtime +14 -delete 2>/dev/null || true
exec flock -n /tmp/scraper-data-gitgit.scrape.lock \
  .venv/bin/python -m scraper --full-text --full-text-limit 30 >> "$LOG" 2>&1
