#!/usr/bin/env bash
#
# One-shot setup for a local test run.
#
#   ./setup.sh you@example.edu
#
# Creates the virtualenv, generates an admin key, enrols the email,
# then prints the two URLs you need and starts the server.
set -euo pipefail

cd "$(dirname "$0")"

EMAIL="${1:-}"
if [[ -z "$EMAIL" ]]; then
  echo "Usage: ./setup.sh your-email@example.edu" >&2
  exit 1
fi

PY=./.venv/bin/python
if [[ ! -x "$PY" ]]; then
  echo "==> Creating the virtualenv"
  python3 -m venv .venv
fi

echo "==> Installing dependencies"
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

# Keep an existing key: regenerating it would lock out a phone that is
# already registered against this backend.
if [[ -f .env ]] && grep -q '^ADMIN_API_KEY=.\+' .env; then
  echo "==> Keeping the existing admin key in .env"
else
  echo "==> Generating an admin key"
  ADMIN_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  cat > .env <<ENVFILE
DATABASE_URL=sqlite:///./scraper.db
ADMIN_API_KEY=${ADMIN_KEY}
APPROVED_PARTICIPANTS_CSV=./approved_participants.csv
PAIRING_WINDOW_SECONDS=900
# Only app.youtube needs this; everything else runs without it.
YOUTUBE_API_KEY=
ENVFILE
fi

ADMIN_KEY="$(grep '^ADMIN_API_KEY=' .env | cut -d= -f2-)"

if [[ ! -f approved_participants.csv ]]; then
  echo "email,participant_id,note" > approved_participants.csv
fi

if grep -qi "^${EMAIL}," approved_participants.csv; then
  echo "==> ${EMAIL} is already enrolled"
else
  NEXT="$(awk -F, 'NR>1 && $2 ~ /^P[0-9]+$/ {n=substr($2,2)+0; if (n>m) m=n} END {printf "P%03d", m+1}' \
          approved_participants.csv)"
  echo "${EMAIL},${NEXT},pilot" >> approved_participants.csv
  echo "==> Enrolled ${EMAIL} as ${NEXT}"
fi

# The phone needs this machine's address on the Wi-Fi; localhost is the
# phone's own loopback and will not reach here.
LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then
  for iface in en0 en1 en2; do
    LAN_IP="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    [[ -n "$LAN_IP" ]] && break
  done
fi
if [[ -z "$LAN_IP" ]] && command -v hostname >/dev/null 2>&1; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi

echo
echo "================================================================"
if [[ -n "$LAN_IP" ]]; then
  echo "  ON THE PHONE, enter this as the server address:"
  echo
  echo "      http://${LAN_IP}:8000"
  echo
  echo "  Check it first in the phone's browser:"
  echo "      http://${LAN_IP}:8000/healthz     -> {\"status\":\"ok\"}"
else
  echo "  Could not detect this machine's Wi-Fi address."
  echo "  Find it under System Settings > Wi-Fi > Details > TCP/IP,"
  echo "  then use http://THAT-ADDRESS:8000 on the phone."
fi
echo
echo "  ON THIS MAC, open the dashboard:"
echo
echo "      http://localhost:8000/dashboard?key=${ADMIN_KEY}"
echo
echo "  Both devices must be on the same Wi-Fi."
echo "  Stop the server with Ctrl-C."
echo "================================================================"
echo

exec ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
