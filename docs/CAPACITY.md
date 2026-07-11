# Capacity & Concurrency — measured

Measured on the dev laptop (Docker Desktop, Postgres 16 container, single small
`api` container). Indicative, not a production benchmark, but establishes headroom.

## Money-path concurrency (correctness under contention)

Real-thread tests against shared Postgres (`tests/test_concurrency.py`):

| Scenario | Result |
|---|---|
| 20 identical M-Pesa callbacks fired in parallel | credited **exactly once** (1 sale + 1 commission line, wallet KSh 97 not 20×, 1 session) |
| 10 devices redeem the same voucher simultaneously | **1 success, 9 rejected**, 1 session — no double-spend |

Guaranteed by `select_for_update` row locks + DB unique constraints
(`ledger_unique_tx_entry_type`, voucher status check), not by luck.

## HTTP throughput (captive-portal read path, `/plans/?router=`, 50 concurrent)

| Server | Throughput | p50 | p90 | p99 | Errors |
|---|---|---|---|---|---|
| Django dev server (`runserver`, single-threaded) | 12 req/s | 4434 ms | 4578 ms | 5540 ms | 0/300 |
| **Gunicorn, 3 workers (production path)** | **132 req/s** | **308 ms** | **639 ms** | **782 ms** | 0/300 |

The dev server serializes requests — never use it for load. Production uses
gunicorn (see `backend/Dockerfile` CMD). 132 req/s on one 3-worker container is
~11M req/day; scale via worker count, DB connection pooling, and caching the
per-tenant plans list.

## Production scaling notes (when needed)

- Increase gunicorn `--workers` (2×CPU+1) and run multiple `api` replicas behind
  the reverse proxy.
- Add a PgBouncer connection pool once replicas × workers approaches Postgres
  `max_connections`.
- Cache `GET /plans/` per tenant (rarely changes) — removes the DB hit from the
  hottest public endpoint.
- Celery worker concurrency scales provisioning/SMS independently of web tier.
