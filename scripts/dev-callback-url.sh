#!/bin/bash
# Point M-Pesa's callback at your CURRENT ngrok tunnel — in one command.
#
# WHY THIS EXISTS: ngrok's free tunnel gets a NEW random URL every time it restarts.
# When it rotates, .env still holds the old dead URL, so Safaricom's STK callback POSTs
# into a void, every payment falls back to slow reconciliation, and the hotspot "won't
# connect". This reads the live URL from ngrok's local API, writes it into .env, and
# restarts the API so it takes effect.
#
# USAGE:
#   1. In one terminal:  ngrok http 8000
#   2. In another:       ./scripts/dev-callback-url.sh
set -euo pipefail

ENV_FILE="$(dirname "$0")/../.env"

URL=$(curl -s http://localhost:4040/api/tunnels \
  | grep -o '"public_url":"https://[^"]*"' \
  | head -1 | sed 's/"public_url":"//;s/"$//')

if [ -z "${URL:-}" ]; then
  echo "✗ No ngrok tunnel found. Start it first:  ngrok http 8000" >&2
  exit 1
fi

echo "→ Current ngrok URL: $URL"

# Confirm it actually reaches the callback endpoint (not an ngrok error page).
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  "$URL/api/v1/payments/callback/dev-callback-token/" \
  -H "Content-Type: application/json" -d '{}' || true)
if [ "$CODE" = "404" ]; then
  echo "✗ Tunnel is up but the callback path 404s — is the API running on :8000?" >&2
  exit 1
fi

# Replace (or add) the line in .env.
if grep -q '^DARAJA_CALLBACK_BASE_URL=' "$ENV_FILE" 2>/dev/null; then
  sed -i "s|^DARAJA_CALLBACK_BASE_URL=.*|DARAJA_CALLBACK_BASE_URL=$URL|" "$ENV_FILE"
else
  echo "DARAJA_CALLBACK_BASE_URL=$URL" >> "$ENV_FILE"
fi
echo "→ Wrote it to .env"

# --build and ALL services on purpose. A payment is only delivered if the WORKER is
# alive too — and the worker/beat run the same image as the API. Rebuilding just the API
# after a dependency change once left the worker crash-looping on a missing module,
# silently, so paid customers never got provisioned. Never rebuild one; rebuild all.
docker compose up -d --build >/dev/null
echo "✓ Rebuilt & restarted api + worker + beat. Callbacks now reach $URL."
echo "  Verifying the worker came up clean…"
sleep 5
if docker compose logs worker --since 20s 2>&1 | grep -q "ModuleNotFoundError\|Traceback"; then
  echo "  ✗ WORKER IS CRASHING — payments will NOT provision. Check: docker compose logs worker" >&2
  exit 1
fi
echo "  ✓ Worker healthy. Pay now — it will connect within seconds."
