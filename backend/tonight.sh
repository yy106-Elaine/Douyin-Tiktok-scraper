#!/bin/bash
# Will the 03:00 run do what today's runs did? Checked before it runs.
#
#     ./tonight.sh
#
# Read-only: it opens no browser, touches no profile, and writes
# nothing. Every line is a thing that has gone wrong at least once.
set -u
cd "$(dirname "$0")"
PY=./.venv/bin/python
ok=0; bad=0
yes() { printf '  \033[32mok\033[0m   %s\n' "$1"; ok=$((ok+1)); }
no()  { printf '  \033[31mNO\033[0m   %s\n' "$1"; bad=$((bad+1)); }

echo
echo "Will tonight's 03:00 run do what today's runs did?"
echo

# 1. Is there a job at all, and did it last exit cleanly?
if launchctl list 2>/dev/null | grep -qi "edu.wellesley.scraper.douyin"; then
  status=$(launchctl list 2>/dev/null | awk '/edu.wellesley.scraper.douyin/ {print $2}')
  if [[ "$status" == "0" ]]; then
    yes "the 03:00 job is loaded and last exited 0"
  else
    no "the 03:00 job is loaded but last exited $status -- read logs/daily-*.log"
  fi
else
  no "no 03:00 job is loaded. Reload it:  ./install-daily.sh"
fi

# 2. The image blocking. Default off since 10-14; the day it was on
#    cost 5-60% of every pass and turned removals into unknowns.
if grep -q '"--light"' app/daily.py && ! grep -q 'light=args.heavy' app/daily.py; then
  yes "images are not blocked (--light is opt-in, nothing passes it)"
else
  no "the image blocking may be back on -- see METHODOLOGY 8b"
fi
if grep -q -- "--light" daily.sh; then
  no "daily.sh passes --light"
else
  yes "daily.sh does not pass --light"
fi

# 3. One browser, not two. Two on one account invented removals for
#    five days.
if grep -q 'DOUYIN_PARALLEL="${DOUYIN_PARALLEL:-0}"' daily.sh; then
  yes "the two Douyin passes run one after the other, not at once"
else
  no "daily.sh may run two browsers on one account -- see METHODOLOGY 8b"
fi

# 4. The third removal evidence, which went unread for a month.
if grep -q "API_FILTERED" app/daily.py && grep -q "filtered_out" app/daily.py; then
  yes "a filtered post is read as gone, with the reason Douyin gives"
else
  no "filter_detail is not being read -- removals will be filed as unknown"
fi
if "$PY" - <<'PY' 2>/dev/null
from app.models import LinkCheck
raise SystemExit(0 if hasattr(LinkCheck, "filter_reason") else 1)
PY
then
  yes "the reason has a column to land in"
else
  no "link_checks.filter_reason is missing"
fi

# 5. The page she reads in the morning.
if grep -q "app.report" daily.sh; then
  yes "the nightly run regenerates takedowns.html"
else
  no "nothing regenerates takedowns.html -- the morning page will be stale"
fi
if grep -q -- "--outreach" daily.sh; then
  yes "with the contact list"
else
  no "the contact list will be missing from the page"
fi

# 6. The session. Checked last and with a window, because asking
#    takes the profile and because a headless answer has been wrong.
echo
# The page-reading commands by name, not "-m app." -- that also
# matches this script's own python and a pytest run, and reported a
# pass in progress on a machine where nothing was running.
holder=$(pgrep -fl "python.* -m app\.\(daily\|fetch_videos\|fetch_authors\|download_videos\|login\|peek\)" 2>/dev/null)
if [[ -n "$holder" ]]; then
  echo "  A pass is running now, so the session is not checked here."
  echo "  It is in use, which is itself the answer."
else
  echo "  Session not checked: it needs a window. When nothing is running:"
  echo "      ./.venv/bin/python -m app.login --platform douyin --check"
  echo "  If that says the site is asking to sign in, tonight's run reads"
  echo "  nothing at all -- sign in before bed."
fi

echo
printf '  %d ok, %d to fix\n\n' "$ok" "$bad"
[[ "$bad" -eq 0 ]]
