# WIFI.OS — WISP Hotspot Billing System

Enterprise-grade WiFi hotspot billing for a Kenyan WISP: M-Pesa STK Push payments,
MikroTik provisioning, vouchers, and bulk client messaging. Single-operator today,
SaaS-ready by design (every core model is operator-scoped).

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, Django 5 + DRF, PostgreSQL 16, Celery + Redis |
| Admin UI | React 19 + Vite + Tailwind v4 (`admin-ui/`, port 4600) |
| Captive portal | React + Vite (`portal/`, planned) |
| Payments | Safaricom Daraja STK Push (sandbox by default) |
| Provisioning | MikroTik RouterOS v7 REST over WireGuard (adapter pattern; RADIUS can slot in later) |
| Messaging | Africa's Talking SMS / WhatsApp Cloud API (provider pattern) |

## Quick start (local dev)

```bash
# Backend — full stack: Django API :8000, Postgres, Redis, Celery worker + beat
docker compose up
# API docs:    http://localhost:8000/api/v1/schema/swagger-ui/
# Django admin: http://localhost:8000/admin/  (dev login: 254700000000 / admin12345)

# Admin UI
cd admin-ui && npm install && npm run dev   # http://localhost:4600
```

`docker compose up` runs migrations and seeds dev data (operator, 5 plans, a dummy
router, superuser) automatically via `manage.py seed_dev`.

## Tests & lint

```bash
docker compose run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test api sh -c "ruff check . && pytest"
```

The suite prioritizes the money paths: M-Pesa callback idempotency, payment →
provisioning flow, session expiry, voucher single-use. CI runs the same on GitHub Actions.

## Configuration

Copy `backend/.env.example` and fill in Daraja sandbox credentials from
https://developer.safaricom.co.ke. Everything runs against the sandbox until you
set production values. See `docs/ARCHITECTURE.md` for the full design.
