#!/bin/bash
# Everything, in one screen, after a night's runs.
#
#     ./checkup.sh              # today
#     ./checkup.sh 2026-10-13   # a past day's logs
#
# Read-only. It opens no browser, touches no profile, writes
# nothing, and can be run while a pass is going.
#
# Seven questions, in the order they matter the morning after:
#   1. did the passes run, and did they read anything
#   2. is the unreadable rate back to where it was before 10-05
#   3. what is still owed a check
#   4. what the collection now says
#   5. is anything still unreadable right now
#   6. where recruitment has got to
#   7. is tonight's job going to run
set -u
cd "$(dirname "$0")"
PY=./.venv/bin/python
day="${1:-$(date +%F)}"

rule() { printf '\n\033[1m%s\033[0m\n' "$* ----------------------------------" | cut -c1-80; }

rule "1. last night's passes ($day)"
shopt -s nullglob
logs=(logs/"$day"-*.log)
shopt -u nullglob
if (( ${#logs[@]} == 0 )); then
  echo "  no logs for $day. Either nothing ran, or it is early and the"
  echo "  03:00 job writes to logs/daily-$day.log — check that name too."
else
  for log in "${logs[@]}"; do
    name=$(basename "$log" .log)
    # Only an app.daily pass ends with a "read N; ..." summary.
    # `resolve` and `fetch_authors` are different programs with
    # different last words, and judging them by daily's made the
    # first run of this script report two finished steps as DID NOT
    # FINISH -- a false alarm in the one place that exists to raise
    # true ones.
    tail=$(grep -E "^read [0-9]+;" "$log" | tail -1)
    if [[ -n "$tail" ]]; then
      printf '  %-34s %s\n' "$name" "$tail"
      continue
    fi
    last=$(grep -o '\[[0-9]\{1,\}/[0-9]\{1,\}\]' "$log" | tail -1)
    if [[ -n "$last" ]]; then
      # It counted pages to the end and simply does not print
      # daily's summary.
      done_n=${last#[}; done_n=${done_n%%/*}
      total=${last##*/}; total=${total%]}
      if [[ "$done_n" == "$total" ]]; then
        printf '  %-34s finished %s\n' "$name" "$last"
      else
        printf '  %-34s DID NOT FINISH  (stopped at %s)\n' "$name" "$last"
      fi
      continue
    fi
    # No page counter at all: resolve and the like. The only thing
    # that can be said is whether it ran and said nothing alarming.
    if grep -qiE "traceback|error|refused|SystemExit" "$log"; then
      printf '  %-34s ERRORS — read the log\n' "$name"
    else
      printf '  %-34s ran, no page counter (ok)\n' "$name"
    fi
  done
fi

rule "2. where the unreadable pages sat"
# The number this week was about. Anything over a few percent means
# the 10-05 regression is not the whole story after all.
$PY -m app.logshape logs/"$day"-*.log logs/daily-"$day".log 2>/dev/null \
  || echo "  no logs to read"

rule "3. what is still owed a check"
$PY -m app.recheck --status 2>&1 | sed 's/^/  /'

rule "4. what the collection says"
$PY -m app.analyse 2>&1 | sed 's/^/  /'

rule "5. unreadable right now (last 24h)"
for platform in douyin douyin_note tiktok; do
  count=$($PY -m app.unreadable --platform "$platform" --hours 24 2>/dev/null | wc -l | tr -d ' ')
  printf '  %-14s %s\n' "$platform" "$count"
done
echo "  (these are ids whose LATEST check read nothing; re-read with"
echo "   --only-from after ./.venv/bin/python -m app.unreadable > file)"

rule "5b. removals a later check undid"
# The other half of the 10-05 regression, if there is one. A
# removal here is inferred from the record that came back belonging
# to a different post -- which a page that failed to load its own
# content and fell through to a recommendation also produces.
for platform in douyin douyin_note; do
  $PY -m app.recanted --platform "$platform" --days 14 2>&1 \
    | sed "s/^/  /" | head -24
  echo
done

rule "6. recruitment"
$PY -m app.outreach --status 2>&1 | sed 's/^/  /'

rule "7. tonight's job"
if command -v launchctl >/dev/null; then
  found=$(launchctl list 2>/dev/null | grep -i wellesley)
  if [[ -z "$found" ]]; then
    echo "  NOT LOADED — nothing will run at 03:00. Reload:"
    echo "      ./install-daily.sh"
  else
    echo "$found" | sed 's/^/  /'
    echo "  (first column is the last exit status: 0 is a clean run)"
  fi
fi
# A browser left behind by an interrupted run holds the profile and
# makes the next job stand down. Twice now.
orphan=$(pgrep -fl "user-data-dir=.*browser-profile" 2>/dev/null)
driver=$(pgrep -fl "python.* -m app\." 2>/dev/null)
if [[ -n "$orphan" && -z "$driver" ]]; then
  echo
  echo "  WARNING: a Chromium is holding a profile with no Python driving it."
  echo "  That is wreckage from an interrupted run, and tonight's job will"
  echo "  stand down for it. Clear it:"
  echo "      pkill -f 'user-data-dir=.*browser-profile'"
fi

rule "8. session"
echo "  not checked here: it needs a window, and opening one would"
echo "  take the profile from whatever is running. When you want it:"
echo "      ./.venv/bin/python -m app.login --platform douyin --check"
echo
