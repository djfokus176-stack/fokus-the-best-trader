#!/usr/bin/env bash
# Research-only download of actual Dukascopy usa500idxusd M15 BID and ASK.
# Identical time range and canonical file names as Windows downloader.
set -euo pipefail
OUT="${1:-DANE_SP500_WAVE_M15}"
mkdir -p "$OUT"
for side in bid ask; do
  while read -r start end; do
    name="usa500_m15_${side}_${start}_${end}"
    if [[ -s "$OUT/$name.csv" ]]; then
      echo "CACHED $name"
      continue
    fi
    echo "DOWNLOADING $name"
    npx --yes dukascopy-node@1.51.1 -i usa500idxusd \
      -from "$start" -to "$end" -t m15 -p "$side" -f csv -v \
      -dir "$OUT" -fn "$name" --cache \
      --cache-path "$OUT/.dukascopy-cache" --retries 3 \
      --batch-size 5 --batch-pause 2000
    [[ -s "$OUT/$name.csv" ]] || {
      echo "MISSING $name.csv - aborting; no invented OHLC" >&2
      exit 1
    }
  done <<'DATES'
2021-11-11 2022-11-11
2022-11-11 2023-11-11
2023-11-11 2024-11-11
2024-11-11 2025-11-11
2025-11-11 2026-11-11
DATES
done
echo "SOURCE_DOWNLOAD_COMPLETE: 10 yearly BID/ASK pieces."
