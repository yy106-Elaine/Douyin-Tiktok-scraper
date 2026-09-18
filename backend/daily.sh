#!/usr/bin/env bash
#
# One day's collection, for launchd or cron. Safe to run twice: every
# step de-duplicates, so a manual run after a scheduled one costs a
# little quota and changes nothing else.
#
#   ./daily.sh              # run it now
#   ./install-daily.sh      # schedule it at 09:00 every day
#
# Each step is run separately and a failure is recorded rather than
# fatal. A YouTube quota error must not stop the re-check: the
# re-check is the measurement, and a day missed there widens the
# removal window for every video due that day.

cd "$(dirname "$0")"

PY=./.venv/bin/python
LOG_DIR=logs
BACKUP_DIR=backups
KEEP_BACKUPS=30
WINDOW_HOURS="${WINDOW_HOURS:-72}"

mkdir -p "$LOG_DIR" "$BACKUP_DIR"
LOG="$LOG_DIR/daily-$(date +%F).log"

say() { printf '%s  %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }

run() {
  local label="$1"; shift
  say "-- $label"
  if "$@" >>"$LOG" 2>&1; then
    say "   ok"
  else
    say "   FAILED (exit $?) -- see $LOG"
    FAILURES="${FAILURES}${label} "
  fi
}

FAILURES=""
say "=== daily run starting"

# Before anything writes: there is no other copy of this database.
if [[ -f scraper.db ]]; then
  cp scraper.db "$BACKUP_DIR/scraper-$(date +%F).db"
  say "-- backed up to $BACKUP_DIR/scraper-$(date +%F).db"
  # Keep a month. Old copies are what make a bad re-mark recoverable.
  ls -1t "$BACKUP_DIR"/scraper-*.db 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) \
    | while read -r old; do rm -f "$old"; done
fi

run "youtube collect" "$PY" -m app.youtube collect \
    --keywords keywords.txt --hours "$WINDOW_HOURS"
run "resolve links" "$PY" -m app.resolve
run "mark relevance" "$PY" -m app.relevance
run "recheck links" "$PY" -m app.recheck

if [[ -n "$FAILURES" ]]; then
  say "=== finished with failures: $FAILURES"
  exit 1
fi
say "=== finished cleanly"
