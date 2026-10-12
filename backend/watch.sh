#!/bin/bash
# One window that says where every pass has got to.
#
#     ./watch.sh            # today's logs, refreshing every 10s
#     ./watch.sh 3          # every 3 seconds
#     ./watch.sh 10 2026-10-12
#
# The passes write to a log each and the day log only hears from them
# every five minutes, so watching a run meant either three terminals
# or a five-minute wait to learn whether anything was happening. This
# reads the same `[n/total]` lines the passes print and shows all of
# them on one screen.
#
# Read-only: it opens nothing, touches no profile, and can be started
# and stopped at any point in a run. Ctrl+C to leave.
set -u
cd "$(dirname "$0")"

every="${1:-10}"
day="${2:-$(date +%F)}"

bar() {  # a filled bar for a 0-100 percentage, 24 cells wide
  local pct="$1" cells=24 filled i out=""
  filled=$(( pct * cells / 100 ))
  for ((i = 0; i < cells; i++)); do
    if (( i < filled )); then out+="#"; else out+="."; fi
  done
  printf '%s' "$out"
}

while :; do
  clear
  printf '%s   every %ss, Ctrl+C to stop\n\n' "$(date '+%F %H:%M:%S')" "$every"

  shopt -s nullglob
  logs=(logs/"$day"-*.log)
  shopt -u nullglob

  if (( ${#logs[@]} == 0 )); then
    echo "  no pass logs for $day yet"
  fi

  for log in "${logs[@]}"; do
    name=$(basename "$log" .log)
    name=${name#"$day"-}

    last=$(grep -o '\[[0-9]\{1,\}/[0-9]\{1,\}\]' "$log" 2>/dev/null | tail -1)
    done_n=${last#[}; done_n=${done_n%%/*}
    total=${last##*/}; total=${total%]}

    # Unreadable so far, which is the number that says whether the
    # site is answering. A run that is moving and reading nothing
    # looks healthy on a progress bar alone.
    # `grep -c` already prints 0 when it finds nothing; it just
    # exits 1 as well, and an `|| echo 0` on the end made the count
    # "0\n0" on every quiet log.
    blank=$(grep -c "nothing readable" "$log" 2>/dev/null) || true
    blank=${blank:-0}

    if [[ -z "$last" ]]; then
      printf '  %-10s starting\n' "$name"
      continue
    fi

    pct=$(( done_n * 100 / (total > 0 ? total : 1) ))
    share=$(( blank * 100 / (done_n > 0 ? done_n : 1) ))
    printf '  %-10s %s %3d%%  %5d/%-5d  unreadable %4d (%d%%)\n' \
      "$name" "$(bar "$pct")" "$pct" "$done_n" "$total" "$blank" "$share"
  done

  # Whether anything is actually running, so a finished run does not
  # sit there looking like a stalled one.
  echo
  # Counted with wc, because BSD pgrep has no -c and prints its
  # usage instead -- which is what it did on the first real run.
  running=$(pgrep -f "python.* -m app\.daily" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "${running:-0}" -gt 0 ]]; then
    printf '  %s pass(es) running\n' "$running"
    # Only the scheduled job redirects into a log; a run started by
    # hand prints to its own terminal and leaves nothing here. The
    # bars above then belong to this morning's finished job and sit
    # perfectly still while real work goes by -- which has already
    # been read once as "it is stuck".
    # -mmin rather than -newermt: BSD find has the first everywhere
    # and the second only on some versions.
    if (( ${#logs[@]} == 0 )) || [[ -z "$(find logs -name "$day-*.log" \
          -mmin -3 2>/dev/null)" ]]; then
      echo "  NOTE: no log has been written in the last 3 minutes, so a"
      echo "  pass running now is one started by hand. Its progress is in"
      echo "  its own terminal; the bars above are an earlier run."
    fi
  else
    printf '  no app.daily running — the passes above have finished\n'
  fi

  sleep "$every"
done
