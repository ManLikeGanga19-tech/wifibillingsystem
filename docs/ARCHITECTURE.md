# Architecture

## Overview

```
customer phone ──► portal (React) ──► Django REST API ──► Daraja STK Push
                                          │  ▲
                     Safaricom callback ──┘  │ poll status
                                          ▼
                                   Celery worker ──► ProvisioningAdapter ──► MikroTik (REST over WireGuard)
                                   Celery beat  ──► expiry sweep / reconciliation / router health
admin staff ──► admin-ui (React) ──► same API (JWT) ──► bulk SMS/WhatsApp via provider adapters
```

## Key decisions

- **Tenancy**: single WISP now; every core model has an `operator` FK (`core.Operator`)
  so multi-WISP SaaS is a later feature, not a rewrite. Daraja credentials can live
  per-operator (encrypted) and fall back to env vars.
- **Identity**: custom `accounts.User`, phone number (`2547XXXXXXXX`) is the username.
  Hotspot customers are passwordless rows; staff log in with phone + password, roles
  via Django Groups (owner / manager / support).
- **Provisioning**: `ProvisioningAdapter` ABC (`apps/provisioning/adapters/`) with
  `activate_user`, `suspend_user`, `get_active_sessions`, `test_connection`.
  Implementations: `MikroTikRestAdapter` (RouterOS v7 REST), `DummyAdapter` (dev/tests).
  Chosen per-router via `Router.provisioning_backend`, so a RADIUS adapter drops in later.
  Adapter calls happen **only in Celery tasks**, never in the request cycle.
- **Router reachability**: routers dial WireGuard tunnels to the server;
  `Router.management_host` stores the tunnel IP. Public IPs also work.
- **Belt and braces expiry**: `limit-uptime` is set on the MikroTik hotspot user at
  activation (router cuts off even if the server is down) *and* a beat task sweeps
  expired sessions every minute.

## Payment flow (money path)

1. `POST /api/v1/payments/stk-push/` → pending `Transaction` → Daraja STK Push →
   returns `public_id`; portal polls `GET /api/v1/payments/status/<public_id>/`.
2. Safaricom hits `POST /api/v1/payments/callback/<token>/` (token 404s strangers).
   Processing is **idempotent on CheckoutRequestID**: row lock + terminal-status check;
   raw JSON stored verbatim before parsing; always answers 200.
3. On success, `provision_transaction` is enqueued via `transaction.on_commit`
   (retry w/ exponential backoff, max 5) → creates `Session` → adapter activates.
4. **Reconciliation** (beat, 5 min): pending transactions older than 2 min are settled
   via `stkpushquery` — lost callbacks are a fact of life.
5. **Expiry** (beat, 1 min): filtered-UPDATE status flip prevents double suspends.

## Apps

| App | Owns |
|---|---|
| `core` | Operator (tenant), AuditLog, encrypted field, phone normalization, stats endpoint |
| `accounts` | custom User (phone identity), JWT auth, subscribers API |
| `plans` | Plan (public list for portal, staff CRUD) |
| `payments` | Transaction, Daraja client, callback, reconciliation |
| `provisioning` | Router, Session, adapters, expiry/health tasks |
| `vouchers` | Voucher batches (unambiguous codes), single-use redemption |
| `notifications` | Campaign/Message, Africa's Talking SMS + WhatsApp Cloud providers |

## Phase 2 parking lot

PPPoE monthly billing + invoices, RADIUS adapter, C2B paybill confirmation URLs,
SMS payment receipts, operator self-signup (SaaS billing), per-site revenue reports.
