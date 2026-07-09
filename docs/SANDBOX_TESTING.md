# Daraja Sandbox: End-to-End Payment Test

## One-time setup

1. Sign up / log in at https://developer.safaricom.co.ke
2. **My Apps → Add a new app** — tick **Lipa Na M-Pesa Sandbox**, create.
3. Copy the app's **Consumer Key** and **Consumer Secret** into `.env` at the repo root.
4. Callbacks need a public HTTPS URL. Easiest options:
   - `cloudflared tunnel --url http://localhost:8000` (free, no signup), or
   - `ngrok http 8000`
   Put the printed URL in `.env` as `DARAJA_CALLBACK_BASE_URL=https://<your-tunnel-host>`
5. Restart the stack so the containers pick up the env: `docker compose up -d`

## Fire a test payment

```powershell
# 1. List plans (note a plan id)
curl http://localhost:8000/api/v1/plans/

# 2. Trigger STK Push — sandbox test MSISDN is 254708374149
curl -X POST http://localhost:8000/api/v1/payments/stk-push/ `
  -H "Content-Type: application/json" `
  -d '{"phone": "254708374149", "plan_id": 1}'
# -> {"transaction_id": "<uuid>", "checkout_request_id": "ws_CO_..."}

# 3. Poll status (portal does this automatically later)
curl http://localhost:8000/api/v1/payments/status/<uuid>/
```

In the sandbox, Safaricom auto-completes the payment after a few seconds and POSTs the
callback to your tunnel URL. Watch it arrive:

```powershell
docker compose logs -f api worker
```

Expected sequence: callback hits `/api/v1/payments/callback/<token>/` → transaction
flips `pending → success` → worker provisions a Session on the dummy router →
status poll returns `"status": "success", "session_active": true`.

## What proves it's production-grade

- Re-POST the same callback body: transaction stays `success`, no duplicate session.
- Kill the tunnel before the callback arrives: within ~5 minutes the reconciliation
  beat task queries Daraja directly and settles the transaction anyway
  (`status: reconciled`).
