#!/usr/bin/env bash
# Scraping kategori aktif + gambar + sentimen. Dipanggil cron tiap jam.
# politik, crypto & saham dihentikan 2026-11-23 (akun IG/FB-nya tidak diposting lagi).
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="data/logs/scrape-$(date +%F).log"
find data/logs -name '*.log' -mtime +14 -delete 2>/dev/null || true
exec flock -n /tmp/scraper-data-gitgit.scrape.lock \
  .venv/bin/python -m scraper --category game --full-text --full-text-limit 30 >> "$LOG" 2>&1
