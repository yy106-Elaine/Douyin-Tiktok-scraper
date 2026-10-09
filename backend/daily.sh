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
#: A rehearsal: the same job, started the same way, reading two pages
#: instead of a thousand. It exists because the thing most likely to
#: stop an unattended run is not the code -- it is macOS asking for
#: permission to reach a folder, which it asks of a background job
#: and not of a terminal, so running this script by hand proves
#: nothing about it. REHEARSE=1 opens the browser, reaches the same
#: folders and writes to a status page of its own, leaving the day's
#: measurement alone.
REHEARSE="${REHEARSE:-0}"
if [[ "$REHEARSE" == "1" ]]; then
  ONLY=douyin
  DOUYIN=1
fi
#: Seconds before a Douyin step is cut off, or 0 for no limit, which
#: is the default. There was a four-hour budget here, and it was the
#: wrong instrument: the re-check grows by every post collected --
#: it passed nine hundred pages in its first month -- so a fixed
#: ceiling becomes a pass that is never allowed to finish, and the
#: ids it never reaches are the ones whose removal goes unmeasured.
#:
#: What the budget was really guarding against was a run stuck at a
#: prompt all night, and that is now handled where it happens: the
#: browser waits five minutes for a person, once, and carries on.
DOUYIN_BUDGET="${DOUYIN_BUDGET:-0}"
#: Pages checked within this many hours are skipped. This is for
#: resuming: a pass over a thousand pages takes hours, a network that
#: drops takes it with it, and starting again from the top costs the
#: hours over again.
#:
#: It is not for spacing the daily run, and setting it as if it were
#: silently cancels that run. At 12 hours, a hand-run ending at 20:30
#: left a 06:00 pass with nothing to do: nine and a half hours is
#: inside twelve, so every page collected the evening before was
#: skipped and the morning's measurement did not happen. Six hours is
#: long enough to resume an interrupted pass and short enough that
#: the next scheduled run always covers the whole corpus.
DOUYIN_SKIP_RECENT="${DOUYIN_SKIP_RECENT:-6}"
PROFILE=.browser-profile
#: The second signed-in browser, for running 视频 and 图文 at once.
#:
#: Chromium holds a lock on its profile directory, so two passes
#: cannot share one -- hence a copy, made once from the first. The
#: copy carries the session: the cookies are encrypted against a key
#: held for this user on this machine, not against the directory.
#:
#: One account and one IP either way. Two sessions is twice the
#: request rate on one account, which is the cost; five machines on
#: five IPs under one account is the thing not to do, because that is
#: what a stolen account looks like to a risk system and the account
#: is the one part of this collection that cannot be replaced.
NOTE_PROFILE=.browser-profile-note
#: 0 runs 视频 and 图文 one after the other, as before.
DOUYIN_PARALLEL="${DOUYIN_PARALLEL:-1}"
#: How often the parallel passes report into the main log, in
#: seconds. A multiple of 15, which is how often the wait loop
#: wakes. Five minutes is often enough to tell a slow run from a
#: stopped one, and rare enough not to bury the log.
HEARTBEAT_SECONDS="${HEARTBEAT_SECONDS:-300}"
#: Seconds each 图文 worker waits between pages.
#:
#: Splitting 图文 across two browsers doubled the request rate
#: against one endpoint, and the first run that did it read two
#: thirds of nothing: median 21.8s against the previous day's 5.3s,
#: 1,002 of 1,501 pages unreadable. The site had stopped returning
#: the record and the pass was timing out on every page.
#:
#: Two workers at two seconds is about the rate one worker at no
#: pause was already managing, which is the rate the site tolerated.
#: Halving the wall time was never worth buying it back in pages
#: that answer nothing.
SHARD_PAUSE="${SHARD_PAUSE:-2}"

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
  if [[ "$seconds" -le 0 ]]; then
    # No ceiling: let it take as long as the corpus takes.
    run "$label" "$@"
    return
  fi
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

# Two Douyin passes at once, each in its own browser, each with its
# own log -- interleaved progress lines from two runs are unreadable,
# and the point of the log is to be read afterwards.
#: How far a pass has got, read off its own output.
#:
#: `app.daily` prints `[12/316] ...` per page, flushed. Taking the
#: last one means this reports the pass's own count rather than a
#: second count kept here that could disagree with it.
furthest() {
  local log="$1" label="$2" last
  last=$(grep -o '\[[0-9]\{1,\}/[0-9]\{1,\}\]' "$log" 2>/dev/null | tail -1)
  printf '%s %s' "$label" "${last:-starting}"
}

run_together() {
  local label_a="$1" label_b="$2"; shift 2
  local log_a="$LOG_DIR/$(date +%F)-video.log"
  local log_b="$LOG_DIR/$(date +%F)-note.log"
  local log_c="$LOG_DIR/$(date +%F)-note2.log"

  # 图文 outnumber the videos five to one, so the two browsers used
  # to finish an hour and a half apart: the video pass was done in
  # twenty minutes and its browser then sat idle while 图文 ground on
  # alone. The 图文 list is therefore halved from the start, and the
  # second half begins in the video browser the moment it is free.
  # Two browsers at a time throughout, which is what the account can
  # afford -- the same account on more than that is what a stolen
  # account looks like to a risk system.
  say "-- $label_a, and $label_b in two halves"

  set -m
  "$PY" -m app.daily --platform douyin \
    --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${LIMIT[@]}" \
    >"$log_a" 2>&1 &
  local pid_a=$!
  "$PY" -m app.daily --platform douyin_note --profile "$NOTE_PROFILE" \
    --shard 1/2 --pause "$SHARD_PAUSE" \
    --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${LIMIT[@]}" \
    >"$log_b" 2>&1 &
  local pid_b=$!
  set +m
  local pid_c=""

  # A heartbeat into the main log while they run. Without it the
  # parallel passes write only to their own files, and the log a
  # person is watching says nothing for four hours -- which looks
  # exactly like a run that has hung, and twice now has been treated
  # as one. The counts come from the passes' own `[n/total]` lines,
  # so this reports what they report and invents nothing.
  local code_a=0 code_b=0 code_c=0 waited=0
  while kill -0 "$pid_a" 2>/dev/null || kill -0 "$pid_b" 2>/dev/null \
        || { [[ -n "$pid_c" ]] && kill -0 "$pid_c" 2>/dev/null; }; do
    sleep 15
    waited=$((waited + 15))

    # The video pass is done and its browser is free: start the other
    # half of 图文 in it. `--shard 2/2` is disjoint from the half
    # already running, so neither worker has to know about the other.
    if [[ -z "$pid_c" ]] && ! kill -0 "$pid_a" 2>/dev/null; then
      wait "$pid_a" || code_a=$?
      say "   $label_a done; starting the second half of $label_b in its browser"
      set -m
      "$PY" -m app.daily --platform douyin_note --profile "$PROFILE" \
        --shard 2/2 --pause "$SHARD_PAUSE" \
        --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${LIMIT[@]}" \
        >"$log_c" 2>&1 &
      pid_c=$!
      set +m
    fi

    if (( waited % HEARTBEAT_SECONDS == 0 )); then
      local line
      line="$(furthest "$log_b" "$label_b 1/2")"
      if [[ -n "$pid_c" ]]; then
        line="$line | $(furthest "$log_c" "$label_b 2/2")"
      else
        line="$(furthest "$log_a" "$label_a") | $line"
      fi
      say "   ... $line"
    fi
  done
  # Harmless when already reaped above; bash keeps the status.
  kill -0 "$pid_a" 2>/dev/null && { wait "$pid_a" || code_a=$?; }
  wait "$pid_b" || code_b=$?
  [[ -n "$pid_c" ]] && { wait "$pid_c" || code_c=$?; }

  # An array, because the labels have spaces in them and an
  # unquoted list would split "图文 check 1/2" into three steps.
  local finished=("$label_a:$code_a:$log_a" "$label_b 1/2:$code_b:$log_b")
  [[ -n "$pid_c" ]] && finished+=("$label_b 2/2:$code_c:$log_c")
  local pair label rest code where
  for pair in "${finished[@]}"; do
    label="${pair%%:*}"; rest="${pair#*:}"
    code="${rest%%:*}"; where="${rest#*:}"
    cat "$where" >>"$LOG" 2>/dev/null
    if [[ $code -eq 0 ]]; then
      say "   $label ok"
    else
      say "   $label FAILED (exit $code) -- see $where"
      FAILURES="${FAILURES}${label} "
    fi
  done
}

# The second browser, copied from the first the once. A copy rather
# than a second sign-in: one account, and nothing to scan or type.
ensure_note_profile() {
  [[ -d "$NOTE_PROFILE" ]] && return 0
  if [[ ! -d "$PROFILE" ]]; then
    say "-- no $PROFILE to copy; sign in once first:  python -m app.login"
    return 1
  fi
  say "-- making $NOTE_PROFILE from $PROFILE (one account, second window)"
  # Lock files and the crash state belong to the first browser's run,
  # not to the copy.
  rm -rf "$NOTE_PROFILE.partial"
  cp -R "$PROFILE" "$NOTE_PROFILE.partial" || return 1
  rm -f "$NOTE_PROFILE.partial/SingletonLock" \
        "$NOTE_PROFILE.partial/SingletonCookie" \
        "$NOTE_PROFILE.partial/SingletonSocket" 2>/dev/null
  mv "$NOTE_PROFILE.partial" "$NOTE_PROFILE"
}

FAILURES=""
#: Steps that did not run at all. Not a failure, and not nothing:
#: the measurement for that platform is missing for the day.
SKIPPED=""
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

#: Is the Douyin profile held by a run that is actually working?
#:
#: `pgrep` on the profile path answers "is a browser open", which is
#: not the same question. Twice now a Chromium has outlived the
#: Python that started it -- an interrupted hand-run leaves the
#: browser sitting at about:blank -- and the scheduled job stood down
#: for a corpse. A whole day of Douyin went unchecked and the log
#: still said "finished cleanly".
#:
#: So: the browser is evidence, the Python process is the answer. If
#: a page-reading command is running, a person or a job is using that
#: profile and this run must not touch it. If the browser is there
#: and nothing is driving it, it is wreckage; say so, clear it, and
#: carry on.
#:
#: The trailing space in the pattern matters. Without it
#: `.browser-profile` also matches `.browser-profile-note` and
#: `.browser-profile-tiktok`, so a TikTok run by hand would have made
#: this stand down for a profile it was never going to touch.
profile_held_by_a_run() {
  local pattern="user-data-dir=$PWD/$PROFILE "
  pgrep -f -- "$pattern" >/dev/null 2>&1 || return 1

  local driver
  driver=$(pgrep -f "python.* -m app\.(daily|fetch_videos|fetch_authors|login)" \
      2>/dev/null | head -1)
  if [[ -n "$driver" ]]; then
    # Name it and say how old it is. Standing down for a working run
    # is right; standing down every morning for a run that wedged on
    # Tuesday is a week of missing data, and the two look identical
    # in a log that only says "a run is using it".
    #
    # Not killed from here. A page read is a database write, and a
    # python that is slow is not a python that is finished -- the
    # judgement of whether a long run is still working belongs to
    # the person, who now has the pid and the age to make it with.
    local age
    age=$(ps -o etime= -p "$driver" 2>/dev/null | tr -d ' ')
    say "-- douyin: held by pid $driver, running for ${age:-?}"
    if [[ "$age" == *-* ]]; then
      say "   THAT IS OVER A DAY OLD. A run this old is wedged, not busy:"
      say "   check it, then  kill $driver  and kickstart this job again"
    fi
    return 0
  fi

  say "-- douyin: a browser holds $PROFILE but nothing is driving it"
  say "   (left behind by an interrupted run; clearing it)"
  pkill -f -- "$pattern" 2>/dev/null
  # Chromium's helpers go with the parent, but give them a moment
  # before the next step tries to open the same directory.
  sleep 3
  if pgrep -f -- "$pattern" >/dev/null 2>&1; then
    say "   could not clear it; standing down"
    return 0
  fi
  return 1
}

# Douyin last, and never in the way of the rest. The steps above are
# cheap, they are the measurement for three platforms, and a Douyin
# run that sits at a verification screen must not be what stops them
# from happening.
if [[ "$DOUYIN" == "1" && "$ONLY" != "api" ]]; then
  if profile_held_by_a_run; then
    # Two runs on one browser profile is a lost run and possibly a
    # lost session. A hand-run in another window wins; this one says
    # so and stands down -- and says so loudly, because a skipped
    # Douyin pass is a day of this study's main measurement missing.
    say "-- douyin: SKIPPED, that browser profile is in use by a run"
    say "   (a run by hand is using it; no Douyin check happened today)"
    SKIPPED="${SKIPPED}douyin "
  else
    # A rehearsal reads two pages of each, which is enough to open the
    # browser, sign in, reach the video folder and write a row -- every
    # step that could ask for something -- and not enough to matter.
    LIMIT=()
    if [[ "$REHEARSE" == "1" ]]; then
      LIMIT=(--limit 2)
      say "-- REHEARSAL: two pages each, today's check is left alone"
    fi
    if [[ "$DOUYIN_PARALLEL" == "1" ]] && ensure_note_profile; then
      run_together "douyin video check" "douyin 图文 check"
    else
      run_limited "douyin video check" "$DOUYIN_BUDGET" \
        "$PY" -m app.daily --platform douyin \
        --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${LIMIT[@]}"
      run_limited "douyin 图文 check" "$DOUYIN_BUDGET" \
        "$PY" -m app.daily --platform douyin_note \
        --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${LIMIT[@]}"
    fi
    # The handle is what an interview request is addressed to, and an
    # account only answers while it is still there. The pass above
    # reads the profile of every new account it meets; this is the
    # backlog, and it stops on its own once a round finds nothing.
    #
    # Two rounds, not more. The backlog is now almost entirely
    # accounts that are themselves gone -- a second round over 73 of
    # them recovered one -- so further rounds are requests spent on
    # profiles that do not exist. The new accounts each day are read
    # by the pass above, and the second round is for the handful the
    # site declines to answer for the first time.
    if [[ "$REHEARSE" != "1" ]]; then
      run_limited "douyin 抖音号" "$DOUYIN_BUDGET" \
        "$PY" -m app.fetch_authors --apply --pause 8 --rounds 2
    fi
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
  # A rehearsal must not overwrite the morning's real answer.
  [[ "$REHEARSE" == "1" ]] && STATUS="$STATUS_DIR/rehearsal.txt"
  {
    if [[ -n "$FAILURES" ]]; then
      echo "NEEDS A LOOK -- $FAILURES"
    elif [[ -n "$SKIPPED" ]]; then
      # Not "OK". Nothing broke, and the day's measurement is still
      # missing -- which is the thing the person reads this page to
      # find out.
      echo "DID NOT RUN -- $SKIPPED"
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
if [[ -n "$SKIPPED" ]]; then
  say "=== finished, but did not run: $SKIPPED"
  exit 0
fi
say "=== finished cleanly"
