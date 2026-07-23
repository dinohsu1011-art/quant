#!/bin/bash
# Once-a-day price refresh, driven by launchd (see com.dinohsu.quant-daily.plist).
#
# launchd fires this at login and every 30 minutes the Mac is awake; the guards
# below make it do real work at most once per day, and only when a US session
# has actually closed since the last run. Everything else is a cheap no-op, so a
# laptop that sleeps through the small hours just catches up on the next wake.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
REPORTS="$HOME/Desktop/Obsidian/trading-brain/reports"
LOGS="$REPO/ops/logs"
STAMP="$REPO/ops/.last-run"
DEPLOYED="$REPO/ops/.last-deploy"

cd "$REPO" || exit 1
mkdir -p "$LOGS"
today=$(date +%F)
note() { echo "$(date '+%F %T')  $*" >> "$LOGS/runs.log"; }

# --- guard 1: at most one real run per calendar day -------------------------
[ "$(cat "$STAMP" 2>/dev/null)" = "$today" ] && exit 0

# --- guard 2: network. No stamp on failure, so it retries on the next tick ---
# Yahoo answers a bare curl with 429 even when yfinance's own session succeeds,
# so any HTTP response counts as reachable — only DNS/TCP/TLS failure is a skip.
# GitHub must genuinely be 2xx: without it the refresh can't be published.
if ! curl -s -o /dev/null -m 15 "https://query1.finance.yahoo.com/v8/finance/chart/SPY"; then
  note "skip: yahoo unreachable"
  exit 0
fi
if ! curl -sf -o /dev/null -m 15 "https://github.com"; then
  note "skip: github unreachable"
  exit 0
fi

# --- guard 3: is there a session we don't already have? ---------------------
LOG="$LOGS/$today.log"
target=$("$PY" "$REPO/ops/last_session.py") || { note "skip: session calc failed"; exit 1; }
current=$(grep -o '"as_of":"[^"]*"' "$REPORTS/cube/index.js" 2>/dev/null | head -1 | cut -d'"' -f4)

# --- refresh ----------------------------------------------------------------
if [[ -n "$current" && ! "$current" < "$target" ]]; then
  note "data already current (as_of $current >= last session $target)"
else
  note "refreshing: as_of $current -> target $target"
  start=$(date +%s)
  before=$( [ -f "$LOG" ] && wc -l < "$LOG" || echo 0 )
  "$PY" "$REPO/update.py" >> "$LOG" 2>&1
  status=$?
  took=$(( $(date +%s) - start ))

  if [ $status -ne 0 ]; then
    note "FAILED after ${took}s (exit $status) — see ops/logs/$today.log"
    osascript -e 'display notification "update.py failed — see ops/logs" with title "quant daily refresh"' 2>/dev/null
    exit $status   # no stamp: the next tick retries
  fi

  current=$(grep -o '"as_of":"[^"]*"' "$REPORTS/cube/index.js" | head -1 | cut -d'"' -f4)
  note "refreshed to $current in ${took}s"

  # non-fatal validate findings would otherwise only exist in the per-day log
  tail -n +$((before + 1)) "$LOG" | grep '\[WARN\]' | while read -r w; do
    note "  warn:${w#*\[WARN\]}"
  done
fi

# --- publish ----------------------------------------------------------------
# Tracked separately from the data, so a refresh whose deploy failed republishes
# on the next tick instead of leaving a fresh dataset behind a stale site.
if [ "$(cat "$DEPLOYED" 2>/dev/null)" = "$current" ]; then
  note "site already at $current"
elif "$REPO/ops/deploy.sh" >> "$LOG" 2>&1; then
  note "deployed $current to gh-pages"
  echo "$current" > "$DEPLOYED"
else
  note "DEPLOY FAILED — data is fresh locally, site is stale. see ops/logs/$today.log"
  osascript -e 'display notification "deploy to gh-pages failed" with title "quant daily refresh"' 2>/dev/null
  exit 1   # no stamp: the next tick retries the publish
fi

echo "$today" > "$STAMP"
find "$LOGS" -name '20*.log' -mtime +30 -delete 2>/dev/null
