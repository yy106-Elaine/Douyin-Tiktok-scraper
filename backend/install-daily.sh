#!/usr/bin/env bash
#
# Schedule the day's collection with launchd (macOS). Two jobs:
#
#   edu.wellesley.scraper.douyin   04:00  the signed-in browser pass
#   edu.wellesley.scraper.daily    06:00  YouTube, TikTok, the rest
#
# Two and not one, because the two halves want different hours. The
# Douyin pass opens a window and works through a thousand pages at the
# browser's own pace; before dawn it is in nobody's way and has hours
# of room. The rest is plain requests, costs minutes, and belongs at
# an hour when a failure is read the same morning. They share nothing
# -- the TikTok and YouTube re-checks do not use the browser -- so
# neither waits on the other.
#
#   ./install-daily.sh                  # install and start both
#   HOUR=7 DOUYIN_HOUR=3 ./install-daily.sh
#   ./install-daily.sh --remove         # unschedule both
#
# launchd, not cron, because launchd runs a job it missed once the Mac
# wakes. A laptop is asleep at most fixed times, and a skipped day is
# not recoverable: the videos that disappeared that day are gone.
#
# Hours are the Mac's own local time, so 6 is 6am where the laptop is.
set -euo pipefail
cd "$(dirname "$0")"

HERE="$(pwd)"
DAILY=edu.wellesley.scraper.daily
DOUYIN=edu.wellesley.scraper.douyin
HOUR="${HOUR:-6}"
DOUYIN_HOUR="${DOUYIN_HOUR:-4}"

unschedule() {
  local label="$1"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
}

REHEARSAL=edu.wellesley.scraper.rehearsal

if [[ "${1:-}" == "--remove" ]]; then
  unschedule "$DAILY"
  unschedule "$DOUYIN"
  unschedule "$REHEARSAL"
  echo "Unscheduled. daily.sh can still be run by hand."
  exit 0
fi

# label, hour (empty for no schedule), ONLY, DOUYIN, [REHEARSE]
schedule() {
  local label="$1" hour="$2" only="$3" douyin="$4" rehearse="${5:-0}"
  local plist="$HOME/Library/LaunchAgents/$label.plist"
  local when=""
  if [[ -n "$hour" ]]; then
    when="  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$hour</integer>
    <key>Minute</key><integer>0</integer>
  </dict>"
  fi
  cat > "$plist" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HERE/daily.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ONLY</key><string>$only</string>
    <key>DOUYIN</key><string>$douyin</string>
    <key>REHEARSE</key><string>$rehearse</string>
  </dict>
  <key>WorkingDirectory</key><string>$HERE</string>
$when
  <key>StandardOutPath</key><string>$HERE/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$HERE/logs/launchd.err.log</string>
</dict>
</plist>
PLIST_END
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
}

# label, hour, ONLY, DOUYIN, [REHEARSE]
mkdir -p "$HOME/Library/LaunchAgents" "$HERE/logs"
schedule "$DOUYIN" "$DOUYIN_HOUR" douyin 1
schedule "$DAILY" "$HOUR" api 0
# On no schedule at all: it exists to be kicked by hand. Started the
# same way as the real job, so it meets the same permission prompts --
# which a run from a terminal does not, and which is the whole point.
schedule "$REHEARSAL" "" douyin 1 1

echo "Scheduled, in the Mac's own time zone:"
echo "  ${DOUYIN_HOUR}:00  Douyin -- video check, 图文 check, 抖音号"
echo "  ${HOUR}:00  YouTube collect, resolve, relevance, TikTok re-check"
echo
echo "  Rehearse:        launchctl kickstart -k gui/$(id -u)/$REHEARSAL"
echo "                   (two pages, the real launchd path, today's"
echo "                    check left alone -- this is what shows"
echo "                    whether macOS still asks for permission)"
echo "  Run one now:     launchctl kickstart -k gui/$(id -u)/$DOUYIN"
echo "                   launchctl kickstart -k gui/$(id -u)/$DAILY"
echo "  Watch the log:   tail -f $HERE/logs/daily-\$(date +%F).log"
echo "  Unschedule:      ./install-daily.sh --remove"
echo
echo "The Mac must be awake and online at those times, or within a"
echo "reasonable window after -- launchd runs a missed job on wake."
echo
echo "The Douyin job opens a browser window, so the Mac must also be"
echo "logged in (locked is fine, logged out or shut down is not). It"
echo "runs for as long as the corpus takes -- there is no ceiling, and"
echo "launchd will not start a second copy while one is still going."
echo "A prompt nobody answers waits five minutes, once, then carries on."
