#!/usr/bin/env bash
#
# Schedule daily.sh at 09:00 every day, using launchd (macOS).
#
#   ./install-daily.sh          # install and start
#   ./install-daily.sh --remove # unschedule
#
# launchd, not cron, because launchd runs a job it missed once the Mac
# wakes. A laptop is asleep at most fixed times, and a skipped day is
# not recoverable: the videos that disappeared that day are gone.
set -euo pipefail
cd "$(dirname "$0")"

LABEL=edu.wellesley.scraper.daily
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HERE="$(pwd)"
HOUR="${HOUR:-9}"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Unscheduled. daily.sh can still be run by hand."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HERE/logs"
cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HERE/daily.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$HERE/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$HERE/logs/launchd.err.log</string>
</dict>
</plist>
PLIST_END

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Scheduled: daily.sh runs at ${HOUR}:00 every day."
echo
echo "  Run it now:      launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "  Watch the log:   tail -f $HERE/logs/daily-\$(date +%F).log"
echo "  Unschedule:      ./install-daily.sh --remove"
echo
echo "The Mac must be awake and online at that time, or within a"
echo "reasonable window after -- launchd runs a missed job on wake."
