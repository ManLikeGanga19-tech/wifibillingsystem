#!/bin/bash
# ONE COMMAND to bring the whole dev stack up after a reboot — and wire M-Pesa to it.
#
#   ./scripts/dev-up.sh
#
# It is idempotent: safe to run again any time something feels off. It:
#   1. starts all Docker services (api, worker, beat, db, redis, mailpit)
#   2. starts ngrok if it isn't already running
#   3. points M-Pesa's callback at the current ngrok URL and restarts the API
#   4. checks the worker booted clean (a dead worker = paid customers never connect)
#
# WHY THIS EXISTS: after a reboot, nothing is running and ngrok's free URL has usually
# rotated. Rather than remember four commands, run this one.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▸ 1/4  Starting Docker services…"
docker compose up -d >/dev/null
echo "  ✓ up"

echo "▸ 2/4  Ensuring ngrok is running…"
# A STATIC domain (free, one per ngrok account) makes the URL permanent — it never
# rotates, so the callback never needs re-pointing. Set NGROK_DOMAIN in .env once you've
# claimed one (see scripts/README-ngrok.md).
NGROK_DOMAIN=$(grep -E '^NGROK_DOMAIN=' .env 2>/dev/null | cut -d= -f2- || true)

if curl -s http://localhost:4040/api/tunnels >/dev/null 2>&1; then
  echo "  ✓ already running"
else
  # Detached, so it survives this script exiting. Logs to /tmp for debugging.
  if [ -n "${NGROK_DOMAIN:-}" ]; then
    echo "  (using your static domain $NGROK_DOMAIN — URL will never change)"
    nohup ngrok http 8000 --url="$NGROK_DOMAIN" --log=stdout >/tmp/ngrok.log 2>&1 &
  else
    nohup ngrok http 8000 --log=stdout >/tmp/ngrok.log 2>&1 &
  fi
  disown || true
  for i in $(seq 1 15); do
    curl -s http://localhost:4040/api/tunnels >/dev/null 2>&1 && break
    sleep 1
  done
  echo "  ✓ started"
fi

echo "▸ 3/4  Pointing M-Pesa callback at the current ngrok URL…"
# Reuse the single-purpose helper (updates .env + restarts api + verifies worker).
bash scripts/dev-callback-url.sh | sed 's/^/  /'

echo ""
echo "✅ Ready. Everything is up and M-Pesa callbacks reach your machine."
echo "   Inbox (dev email): http://localhost:8025"
echo "   Note: ngrok's free URL changes each time ngrok restarts. If payments stop"
echo "   connecting later, just run this script again — or claim a free STATIC domain"
echo "   (see scripts/README-ngrok.md) so the URL never changes."
