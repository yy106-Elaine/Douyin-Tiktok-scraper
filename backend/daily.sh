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
#: 1 runs 视频 and 图文 at once, 0 one after the other.
#:
#: Off, though not for the reason first given here. That comment
#: said one pass alone read 241 pages with "~4% unreadable" and two
#: at once 39%, and concluded concurrency. The 4% was wrong: that
#: run failed on 47 of 241, which is 20%. It was confused with an
#: 18-page sample taken under a different setting, and the mistaken
#: number was then used as the evidence for this very switch.
#:
#: Measured alone, on the same code, the share has read 6%, 20% and
#: 79% on three occasions. Concurrency is not the variable: the 79%
#: run had nothing else running.
#:
#: Sequential stays the default anyway, because it costs wall time
#: and nothing else -- a page that answers nothing is read again
#: tomorrow, so the parallel run never finished sooner, it finished
#: earlier and left the work behind. But it is a precaution, not a
#: fix, and the cause is still open.
DOUYIN_PARALLEL="${DOUYIN_PARALLEL:-0}"
#: How the passes drop the app's cached state between pages.
#:
#: `tab` here, and `blank` for a run by hand, because they differ in
#: a way that only matters when somebody is at the machine: a new
#: tab raises Chromium to the front on macOS, which makes the laptop
#: unusable for the hours a pass takes. At three in the morning
#: nobody is typing, so the scheduled job gets the arm with the
#: better reading -- 1 unreadable in 8, and 1 in 18 before that,
#: against 119 in 150 for `blank` on the same corpus the same day.
#:
#: Two samples against one is not settled, which is why this is a
#: variable and not a constant.
FORGET_BY="${FORGET_BY:-tab}"
#: Send the browser window to the Dock while a pass runs.
#:
#: On, now, for the scheduled job as well as for a run by hand. The
#: reason `tab` was chosen above is that at three in the morning
#: nobody is typing, and a new tab raising Chromium to the front
#: therefore costs nothing. That reasoning holds only while the pass
#: finishes before anyone sits down. On 10-22 the video pass was
#: still going at 11:00 -- 304 pages at 1.7 minutes each where the
#: day before they took 2.4 seconds -- and the machine was unusable
#: for the whole morning.
#:
#: The two settings do not fight: `_out_of_the_way()` minimises
#: again after every new tab, and a minimised window is one macOS
#: will not raise. Chromium throttles timers in a window it thinks
#: nobody is watching and the page's own JavaScript is what fetches
#: the record, so the flags that turn that throttling off are set at
#: launch whenever this is on.
MINIMISE="${MINIMISE:-1}"
MIN_FLAG=()
[[ "$MINIMISE" == "1" ]] && MIN_FLAG=(--minimise)
#: How often the parallel passes report into the main log, in
#: seconds. A multiple of 15, which is how often the wait loop
#: wakes. Five minutes is often enough to tell a slow run from a
#: stopped one, and rare enough not to bury the log.
HEARTBEAT_SECONDS="${HEARTBEAT_SECONDS:-300}"

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

  # One worker per endpoint, and that is the whole rule.
  #
  # 图文 outnumber the videos five to one, so the video browser is
  # free after twenty minutes while 图文 grinds on for hours. Filling
  # it with the other half of the 图文 list was the obvious move and
  # it was wrong: two workers on one endpoint read half of nothing.
  #
  # 10-08, one 图文 worker:   1,396 pages, 45 unreadable (3%), median 5.3s
  # 10-09, two, no pause:     1,501 pages, 1,002 unreadable (67%)
  # 10-12, two, 2s pause:     1,339 pages, 676 unreadable (50%), ~20s each
  #
  # The pause did not fix it, because the rate was never the thing
  # being measured: a worker with no pause still takes ~6s a page, so
  # one worker was already only managing a page every seven seconds.
  # Two at two seconds is still roughly double that, and by 10-12 the
  # site was refusing half the records even while each page took
  # twenty seconds -- a quota over a longer window, which slowing
  # down inside one run cannot buy back.
  #
  # And the saving was never real. A page that answers nothing has to
  # be read again another day, so splitting the list did not halve
  # the work, it increased it. The video pass keeps its own browser
  # because it reads a different endpoint, which is the pairing that
  # has always worked.
  say "-- $label_a and $label_b, together"

  set -m
  "$PY" -m app.daily --platform douyin --forget-by "$FORGET_BY" \
    --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${MIN_FLAG[@]}" \
    "${LIMIT[@]}" >"$log_a" 2>&1 &
  local pid_a=$!
  "$PY" -m app.daily --platform douyin_note --profile "$NOTE_PROFILE" \
    --forget-by "$FORGET_BY" \
    --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${MIN_FLAG[@]}" \
    "${LIMIT[@]}" >"$log_b" 2>&1 &
  local pid_b=$!
  set +m

  # A heartbeat into the main log while they run. Without it the
  # parallel passes write only to their own files, and the log a
  # person is watching says nothing for four hours -- which looks
  # exactly like a run that has hung, and twice now has been treated
  # as one. The counts come from the passes' own `[n/total]` lines,
  # so this reports what they report and invents nothing.
  local code_a=0 code_b=0 waited=0
  while kill -0 "$pid_a" 2>/dev/null || kill -0 "$pid_b" 2>/dev/null; do
    sleep 15
    waited=$((waited + 15))
    if (( waited % HEARTBEAT_SECONDS == 0 )); then
      say "   ... $(furthest "$log_a" "$label_a") | $(furthest "$log_b" "$label_b")"
    fi
  done
  wait "$pid_a" || code_a=$?
  wait "$pid_b" || code_b=$?

  local pair label rest code where
  for pair in "$label_a:$code_a:$log_a" "$label_b:$code_b:$log_b"; do
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
    # New phone captures, stitched and read before anything is
    # checked. Until now these lived only in the other half of the
    # job (`resolve`) or nowhere at all (`fetch_videos`, which was
    # always run by hand) -- so a morning's new posts were tracked
    # but had no caption, author or publication time until somebody
    # remembered. The browser pass below then checks them the same
    # night, which is the point: a post collected at 22:00 and first
    # read at 03:00 has a five-hour window on its removal, not a day.
    #
    # `resolve` needs no browser and is safe to repeat: both halves
    # of the job may run it, and the second finds nothing to do.
    # `fetch_videos` does use the signed-in browser, so it goes
    # here, in sequence with the passes that share that profile --
    # never beside them.
    run "resolve links (douyin)" "$PY" -m app.resolve
    if [[ "$DOUYIN_PARALLEL" == "1" ]] && ensure_note_profile; then
      run_together "douyin video check" "douyin 图文 check"
    else
      run_limited "douyin video check" "$DOUYIN_BUDGET" \
        "$PY" -m app.daily --platform douyin --forget-by "$FORGET_BY" \
        --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${MIN_FLAG[@]}" \
        "${LIMIT[@]}"
      run_limited "douyin 图文 check" "$DOUYIN_BUDGET" \
        "$PY" -m app.daily --platform douyin_note --forget-by "$FORGET_BY" \
        --skip-recent "$DOUYIN_SKIP_RECENT" --apply "${MIN_FLAG[@]}" \
        "${LIMIT[@]}"
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
    # After the checks, not before them.
    #
    # These two ran before the checks for one night, 10-21, and that
    # night the video pass read 181 unreadable where the two before
    # it read none, and the 图文 pass recorded 684 removals against a
    # previous high of 113. Both numbers on the one night this
    # ordering was live. That is not proof -- nothing here isolates
    # it -- but it is the only thing that changed, so it moves and
    # tomorrow says whether that was it.
    #
    # The cost of being here instead is small and known: a post
    # collected at 22:00 is still *checked* at 03:00, because the
    # check needs the video id and `resolve` above provides it. Only
    # the caption and the publication time arrive a few hours later.
    run_limited "douyin new captions" "$DOUYIN_BUDGET" \
      "$PY" -m app.fetch_videos --platform douyin --apply \
      "${MIN_FLAG[@]}" "${LIMIT[@]}"
    run_limited "douyin 图文 new captions" "$DOUYIN_BUDGET" \
      "$PY" -m app.fetch_videos --platform douyin_note --apply \
      "${MIN_FLAG[@]}" "${LIMIT[@]}"

    if [[ "$REHEARSE" != "1" ]]; then
      run_limited "douyin 抖音号" "$DOUYIN_BUDGET" \
        "$PY" -m app.fetch_authors --apply --pause 8 --rounds 2 \
        "${MIN_FLAG[@]}"
    fi
  fi
fi

# The page she reads. Regenerated here rather than by hand, because
# "everything is refreshed when I get up" was the whole point of a
# job that runs at three -- and until tonight the HTML was whatever
# was last written by a person, which on one morning was six days
# old and read as current.
#
# Written with the contact list. That names real people and links to
# their profiles, so: it lives outside the repository's tracked
# files, it is not copied to iCloud with the phone status, and
# REPORT_OUTREACH=0 leaves it out for a machine that is not hers.
#
# A rehearsal writes its own file. Overwriting the real page with a
# dry run's numbers is the kind of thing that is only noticed a week
# later.
REPORT_OUT="${REPORT_OUT:-takedowns.html}"
[[ "$REHEARSE" == "1" ]] && REPORT_OUT="takedowns-rehearsal.html"
REPORT_OUTREACH="${REPORT_OUTREACH:-1}"
if [[ "$REPORT_OUTREACH" == "1" ]]; then
  run "takedown page" "$PY" -m app.report --out "$REPORT_OUT" --outreach
else
  run "takedown page" "$PY" -m app.report --out "$REPORT_OUT"
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
