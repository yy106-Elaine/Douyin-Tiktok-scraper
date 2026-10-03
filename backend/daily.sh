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
#
# Douyin is in here now, at the end. It needs the signed-in browser,
# which is why it was left out: a window opens, and once in a while
# the site asks for a verification tap. But the session in
# .browser-profile survives for weeks, so most days nothing is asked
# -- and the 图文 re-check had grown to the better part of a
# thousand pages, which is not something to start by hand at
# midnight. A run that does get asked to verify cannot wait forever,
# so each Douyin step has a time budget and is cut off at it; what it
# did reach is already recorded, and the next day's run carries on
# from there.
#
# Set DOUYIN=0 to leave it out again:  DOUYIN=0 ./daily.sh
#
# What this does NOT do, and why:
#
#  - TikTok pages and files. TikTok is now check-only -- it is kept
#    as a comparison case for removals, and the content analysis is
#    Douyin's. The takedown check below still covers it; nothing
#    fetches its pages or downloads its videos any more.

cd "$(dirname "$0")"

PY=./.venv/bin/python
LOG_DIR=logs
BACKUP_DIR=backups
KEEP_BACKUPS=30
WINDOW_HOURS="${WINDOW_HOURS:-72}"
DOUYIN="${DOUYIN:-1}"
#: Which half of the day's work this run does. `all` is everything,
#: as it always was. The two halves are scheduled separately --
#: Douyin hours before dawn, where a slow browser pass costs nothing
#: and a verification window is not in anybody's way; the rest at a
#: civilised hour -- so they are split rather than ordered:
#:   ONLY=douyin ./daily.sh      the browser pass and nothing else
#:   DOUYIN=0    ./daily.sh      everything else
ONLY="${ONLY:-all}"
#: A Douyin step is cut off after this long. Long enough for a
#: thousand pages at the browser's own pace; short enough that a run
#: stopped at a verification screen does not sit there until morning
#: holding the browser profile.
DOUYIN_BUDGET="${DOUYIN_BUDGET:-14400}"
#: Pages checked within this many hours are skipped, so a hand-run
#: earlier in the day is not repeated and an interrupted run resumes.
DOUYIN_SKIP_RECENT="${DOUYIN_SKIP_RECENT:-12}"
PROFILE=.browser-profile

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

# A step with a time budget. macOS has no `timeout`, so the watchdog
# is written out: SIGINT to the step's whole process group, which
# Python turns into a KeyboardInterrupt and the browser closes with
# it, then SIGKILL thirty seconds later for whatever ignored that. Every video is committed as it is read, so a step
# cut off here loses nothing but the pages it had not reached.
run_limited() {
  local label="$1" seconds="$2"; shift 2
  say "-- $label (up to $((seconds / 60)) min)"
  # `set -m` for the launch: it puts the step in a process group of
  # its own, so the watchdog can signal the browser along with the
  # Python that opened it, and so the step is not started with SIGINT
  # ignored -- which is what a background job in a script otherwise
  # gets, and which would leave nothing but SIGKILL to stop it.
  set -m
  "$@" >>"$LOG" 2>&1 &
  local pid=$!
  set +m
  ( sleep "$seconds"
    kill -INT -"$pid" 2>/dev/null && sleep 30
    kill -9 -"$pid" 2>/dev/null ) >/dev/null 2>&1 &
  local guard=$!
  local code=0
  wait "$pid" || code=$?
  kill "$guard" 2>/dev/null
  wait "$guard" 2>/dev/null
  if [[ $code -eq 0 ]]; then
    say "   ok"
  elif [[ $code -ge 128 ]]; then
    say "   STOPPED at the time budget -- what it reached is recorded;"
    say "   tomorrow's run carries on. If this repeats, the site is"
    say "   probably asking to verify: open the browser and sign in."
    FAILURES="${FAILURES}${label}(budget) "
  else
    say "   FAILED (exit $code) -- see $LOG"
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

if [[ "$ONLY" != "douyin" ]]; then
  run "youtube collect" "$PY" -m app.youtube collect \
      --keywords keywords.txt --hours "$WINDOW_HOURS"
  run "resolve links" "$PY" -m app.resolve
  run "mark relevance" "$PY" -m app.relevance
  # Not the Douyin platforms: see BROWSER_ONLY. This reaches TikTok
  # and YouTube with plain requests, so it shares nothing with the
  # browser pass below and the two can be scheduled hours apart
  # without either waiting on the other.
  run "recheck links" "$PY" -m app.recheck
fi

# Douyin last, and never in the way of the rest. The steps above are
# cheap, they are the measurement for three platforms, and a Douyin
# run that sits at a verification screen must not be what stops them
# from happening.
if [[ "$DOUYIN" == "1" && "$ONLY" != "api" ]]; then
  if pgrep -f "user-data-dir=.*$PROFILE" >/dev/null 2>&1; then
    # Two runs on one browser profile is a lost run and possibly a
    # lost session. A hand-run in another window wins; this one says
    # so and stands down.
    say "-- douyin: skipped, that browser profile is already open"
    say "   (a run by hand is using it; this is not a failure)"
  else
    run_limited "douyin video check" "$DOUYIN_BUDGET" \
      "$PY" -m app.daily --platform douyin \
      --skip-recent "$DOUYIN_SKIP_RECENT" --apply
    run_limited "douyin 图文 check" "$DOUYIN_BUDGET" \
      "$PY" -m app.daily --platform douyin_note \
      --skip-recent "$DOUYIN_SKIP_RECENT" --apply
    # The handle is what an interview request is addressed to, and an
    # account only answers while it is still there. The pass above
    # reads the profile of every new account it meets; this is the
    # backlog, and it stops on its own once a round finds nothing.
    run_limited "douyin 抖音号" 3600 \
      "$PY" -m app.fetch_authors --apply --pause 8 --rounds 4
  fi
fi

# Not a step: the log's own answer to "did this morning's run cover
# everything?".
say "-- freshness"
"$PY" -m app.recheck --status >>"$LOG" 2>&1 || true

# A page small enough to read on a phone, written where the phone can
# reach it. The laptop runs this before dawn and the person is often
# not at it for the rest of the day; the question they have from
# wherever they are is only ever "did it run, and did anything
# break?". iCloud Drive answers that with no service, no account and
# nothing of the collection leaving the machine -- counts and step
# names, never captions, handles or ids.
#
# Overwritten each run, so the Files app shows one file and it is
# always the latest. The dated log stays here in full.
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
STATUS_DIR="${STATUS_DIR:-$ICLOUD/douyin-status}"
if [[ -d "$(dirname "$STATUS_DIR")" ]]; then
  mkdir -p "$STATUS_DIR"
  STATUS="$STATUS_DIR/last-run.txt"
  {
    if [[ -n "$FAILURES" ]]; then
      echo "NEEDS A LOOK -- $FAILURES"
    else
      echo "OK"
    fi
    echo "$ONLY run, finished $(date '+%F %H:%M %Z')"
    echo
    # The lines worth seeing: what each step did, and what it says is
    # still missing. Taken from today's log, which both runs append
    # to, so the morning page shows the night's Douyin pass as well.
    # The step lines carry `say`'s timestamp, and the anchors matter:
    # `-- ` unanchored also matches "gone -- the site served ...",
    # which is every removed video in the run.
    grep -E "^[0-9-]{10} [0-9:]{8}  (--|   (ok|FAILED|STOPPED))|^read |^of those,|account\(s\) still (have no|without)" \
      "$LOG" 2>/dev/null | tail -40
  } > "$STATUS" 2>/dev/null || true
  say "-- status for the phone: $STATUS"
fi

if [[ -n "$FAILURES" ]]; then
  say "=== finished with failures: $FAILURES"
  exit 1
fi
say "=== finished cleanly"
