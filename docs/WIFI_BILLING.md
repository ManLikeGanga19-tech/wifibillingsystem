# Playbook — Deploying the WIIF Billing Platform onto the Contabo VPS

> Enterprise co-hosting + migration playbook for the **WIIF tenant-based billing
> system**, distilled from **two** proven migrations onto this box:
> ShuleHQ (Render/Vercel → Contabo, `v1.0.0`) and **Wooden Houses Kenya
> (2026-07-25)**. The WHK run proved the co-hosting pattern a *second* time and
> paid for several new, concrete gotchas — they're in §6.
>
> Billing gets its own playbook because **money changes the risk calculus**. A
> marketing-site bug is a 500. A billing bug is a double charge, a lost payment,
> a wrong invoice, or a compliance incident. Where the other playbooks optimise
> for availability, this one optimises for **correctness of financial writes**.
>
> Copy this into the WIIF repo and adapt the names (`wiif` → your slug).

---

## 0. The rules that override everything

1. **ShuleHQ *and* Wooden Houses Kenya are both live on this box.** WIIF is the
   **third** tenant. It must never be able to degrade either. When in doubt,
   isolate harder.
2. **Billing handles money. Correctness beats availability for money.** A read
   may degrade; a financial **write** must be correct or **refused**. This is the
   opposite of the login-path "fail open" rule (§6.8 of the second-platform
   playbook) — for money you **fail closed**: a payment you cannot verify is a
   payment you do **not** mark complete.
3. **The box now runs two tenants already.** Capacity, networks, and the shared
   Caddy/Postgres are more contended than when WHK landed. Measure before you add.

---

## 1. What already exists on the VPS (reuse — do NOT rebuild)

| Component | Current state (post-WHK) | How WIIF uses it |
|---|---|---|
| **Contabo VPS** `94.72.102.13` | hardened; now hosts ShuleHQ **and** WHK | WIIF is more containers on the same host. |
| **Caddy** (`sms-caddy`, `:80/:443`) | now edge for **`*.shulehq.co.ke` AND `woodenhouseskenya.com`** — proven multi-domain; Caddyfile at `/opt/shulehq/Caddyfile`, single file, no `sites/` dir | Add a WIIF site block (§5). Same graceful-reload technique (§6.18). |
| **Cloudflare** | authoritative DNS, proxy ON, WAF; per-zone API tokens | New zone/records + a **WIIF-scoped** token. |
| **PostgreSQL 18** (`sms-postgres`) | one instance, now holds `shulehq` **and** `woodenhouses` DBs | **Third DB + third role** — never a second Postgres. |
| **Redis** (`sms-redis`) | shared | WIIF gets its **own logical DB index**; never share key space. |
| **CI ship-don't-pull pipeline** | proven twice (build→`docker save`→ship→`docker load`→compose up) | Replicate with `wiif-*` image names. |
| **Neighbour health checks** | CI verifies ShuleHQ before/after each WHK deploy | Extend to check **both** ShuleHQ and WHK before/after each WIIF deploy. |

**WHK networks already on the box:** `whk-edge-net`, `whk-db-net`. WIIF gets its
own: `wiif-edge-net`, `wiif-db-net`. Attach `sms-caddy` to `wiif-edge-net` and
`sms-postgres` to `wiif-db-net` at runtime (no neighbour restart — see §6.18).

---

## 2. Capacity budget (THREE tenants now — plan hard)

The 8 GB box already carries ShuleHQ (~5.7 GB of ceilings) **plus** WHK (backend
`768m` + frontend `512m`). Before deploying WIIF:

1. **Measure real free headroom now:** `free -m`, `docker stats --no-stream`, and
   sum current `mem_limit`s. Do not deploy blind.
2. **Give every WIIF container hard `cpus` and `mem_limit`.** Keep the sum of
   **all** ceilings across all three tenants under ~7 GB (leave ~1 GB for the OS).
3. **If WIIF doesn't fit, right-size ShuleHQ's generous ceilings down first**
   (it runs in far less), or give the billing platform its **own small VPS** —
   which for a money system is a defensible choice on isolation grounds alone.

Suggested starting ceilings (tune from a load test, not a guess):

| Container | cpus | mem_limit | Notes |
|---|---|---|---|
| api / backend | 1.0 | 512m | raise only if a load test proves need |
| frontend | 0.5 | 512m | standalone/static → near zero |
| **worker (webhooks, reconciliation, dunning)** | 0.5 hard | 512m hard | the async money-mover; never unbounded |

> The WHK backend was throttled by an under-sized cap until a load test proved it.
> Size from evidence: `wrk` + watch `/sys/fs/cgroup/.../cpu.stat` `nr_throttled`.

---

## 3. Isolation checklist (the heart of co-hosting — now with two neighbours)

- [ ] **Separate deploy path** — `/opt/wiif`, never `/opt/shulehq` or `/opt/woodenhouses`.
- [ ] **Separate compose project** — own `docker-compose.prod.yml`, run with `-p wiif`.
- [ ] **Separate Docker networks** — `wiif-edge-net` (Caddy only) + `wiif-db-net`
      (Postgres only). WIIF containers share **no** network with ShuleHQ or WHK app containers.
- [ ] **Separate database + role**, cross-DB access **denied and verified**:
      ```sql
      CREATE ROLE wiif LOGIN PASSWORD '<strong-unique>';
      CREATE DATABASE wiif OWNER wiif;
      REVOKE ALL ON DATABASE shulehq     FROM wiif;
      REVOKE ALL ON DATABASE woodenhouses FROM wiif;
      -- prove it: \c shulehq  → SET ROLE wiif; SELECT * FROM core.tenants;  -- MUST be denied
      ```
- [ ] **Separate Redis logical DB** (e.g. `/2`; `/0` shulehq, `/1` whk).
- [ ] **Hard resource caps** on every container (§2).
- [ ] **Separate GitHub Environment + secrets** (`production-wiif`, `PRODUCTION_ENV`
      scoped to WIIF). Never reuse another tenant's secrets or tokens.
- [ ] **WIIF-scoped Cloudflare token** (Zone:Read + DNS:Edit on the WIIF zone only).
- [ ] **Separate Caddy site block** with its own inlined/enved token (§5, §6.18).
- [ ] **Separate backup schedule/target**, encrypted (financial data — §7).
- [ ] **Deploy safety:** CI checks **ShuleHQ *and* WHK** health before *and* after
      every WIIF deploy. A billing deploy that hurts a neighbour must abort loudly.

---

## 4. Billing-specific guardrails (this REPLACES the AI-agent section)

Money introduces failure modes ordinary apps don't. Each is non-optional.

### 4.1 Financial data integrity
- [ ] **Money is integer minor units (or `DECIMAL`), NEVER float/double.** No
      floating-point anywhere near a currency amount. Store the currency too.
- [ ] **Append-only ledger / double-entry.** Never mutate a posted transaction —
      **reverse** it with a compensating entry. History is immutable.
- [ ] **Exactly-once money movement.** Every charge/refund/payout carries an
      **idempotency key**; replays return the original result, never a second charge.
- [ ] **State machines, not booleans.** An invoice/payment has explicit states
      (`pending → authorized → captured → settled → refunded/failed`); illegal
      transitions are rejected at the DB and app layer.

### 4.2 Payment-provider webhooks (M-Pesa Daraja, Stripe, Flutterwave/Paystack)
Webhooks are **public inbound** — the one place billing must accept traffic it
didn't originate. Treat every one as hostile until proven:
- [ ] **Verify the signature / MAC on every webhook.** Reject unsigned or badly
      signed. An IP allowlist is *not* authentication — do both where possible.
- [ ] **Persist the raw payload BEFORE processing** (audit + replay + debugging).
- [ ] **Idempotent handlers.** Providers retry aggressively; you *will* receive
      duplicates and out-of-order deliveries. De-dupe on the provider event id.
- [ ] **Respond 2xx fast, process async.** Enqueue to the worker; never do ledger
      work inside the HTTP handler (a slow handler = provider retries = duplicates).
- [ ] **M-Pesa Daraja specifics:** STK-push + C2B/B2C callbacks need an **HTTPS,
      publicly reachable** callback URL (via Caddy → WIIF). Sandbox first; the
      callback must return the exact expected JSON or Safaricom retries/faults.
- [ ] **Dedicated Caddy route** for callbacks (e.g. `api.wiif.<domain>/webhooks/*`),
      rate-limited on the real client IP (§6.7), body-size capped.

### 4.3 Multi-tenant isolation (billing = per-tenant money — the core risk)
- [ ] **Every financial row carries `tenant_id`.** Enforce isolation with
      **Postgres Row-Level Security**, not just app-layer `WHERE tenant_id = …`
      (one missing clause = a tenant sees another tenant's money).
- [ ] **Prove cross-tenant denial** the way we prove cross-DB denial: set the
      tenant context, attempt to read another tenant's invoices → **must be empty/denied.**
- [ ] **Never trust a tenant id from the client** for reads/writes of money —
      derive it from the authenticated session/token server-side.

### 4.4 Idempotency, reconciliation & dunning
- [ ] **Idempotency keys** on all mutating payment endpoints (client-supplied,
      stored, unique per operation).
- [ ] **Daily reconciliation job:** provider settlement report vs your ledger.
      Alert on any mismatch to the same pager (ntfy) the watchdog uses.
- [ ] **Never auto-refund/auto-charge from a discrepancy** — flag for a human.
      Automated money movement off a mismatch is how one bug becomes a hundred.
- [ ] **Dunning/retries are idempotent and capped** — a failing charge must not
      loop forever re-billing.

### 4.5 Secrets, keys, PCI scope
- [ ] **Never store raw card data.** Use the provider's tokenization / hosted
      fields so WIIF stays **out of PCI scope**. If you can see a PAN, you've failed.
- [ ] Webhook signing secrets + provider API keys in the env file only,
      **gitignored**, rotated on a schedule and after any exposure.
- [ ] **Sandbox keys never touch prod**, and prod keys never touch a dev machine.
      Separate keys per environment; separate GitHub environment.

### 4.6 Audit, compliance & availability posture
- [ ] **Immutable audit log** of every financial action: who, what, when, amount,
      currency, tenant, provider ref. Append-only; never deleted.
- [ ] **Fail closed on money (§0.2):** if you can't verify a payment/webhook,
      record it as *unconfirmed* and refuse to grant service — never assume success.
- [ ] **Kenya context:** DPA awareness for tenant PII; KRA/eTIMS if you issue tax
      invoices; retain financial records per statutory period.
- [ ] Financial-data backups are **non-negotiable, encrypted, offsite,
      restore-drilled** *before* real money flows (§7).

---

## 5. Deploy / migration sequence (proven twice — with the WHK-verified mechanics)

Same phased approach; each phase gates the next. The **bold** items are
techniques the WHK cutover proved on 2026-07-25.

**Phase 1 — Safety net.** Source (if any) backed up and **restore-verified**
first. "The backup you have never restored does not exist."

**Phase 2 — Provision.** New deploy path, DB + role (cross-DB denial verified),
`wiif-edge-net`/`wiif-db-net`, GitHub environment + secrets, WIIF-scoped CF token,
new image names in CI.

**Phase 3 — Deploy to the box, private.** Ship + `docker load` + compose up with
hard caps. **Pre-issue TLS via Cloudflare DNS-01 so certs are obtained while
public DNS still points elsewhere**, then **verify on the box before any DNS
change**:
```bash
# valid TLS + correct upstream, without the domain pointing here yet:
curl --resolve api.wiif.<domain>:443:127.0.0.1 https://api.wiif.<domain>/health
```
Smoke-test webhooks against **sandbox** provider credentials end-to-end here.

**Phase 4 — Cutover.** Maintenance window → **suspend source writes** → final
backup → migrate → **verify row counts match source exactly, and check the
migration-window delta** (writes to the source *after* the dump live only on the
source — we caught this for WHK by diffing Render vs Contabo). Then:
- **Flip only the app A/CNAME records** to `94.72.102.13` (proxied).
- **NEVER touch `MX`, `mail`, `cpanel`, `ftp`, `webmail`, `webdisk`, `whm`,
  `SPF`/`DKIM`/verification `TXT`** — that's email/hosting, unrelated to the app.
- **Save rollback**: old DNS values (JSON), the on-box `.last_deployed_tag`, and
  the Caddyfile backup.
- Proxied records flip in **seconds** (clients hit Cloudflare, which re-resolves
  the origin) — **provided CF SSL mode is Full(strict)** so it trusts Caddy's
  Let's Encrypt cert.
- Verify from **outside** the box afterward.

**Phase 5 — Burn-in & decommission.** Watch 24–48 h. Confirm WIIF's own backups
fire **unattended** and restore-verify. **Take a final archival dump of the
source, keep the source *suspended not deleted* as rollback, delete only after
burn-in.**

---

## 6. Gotchas we already paid for (the WHK edition adds 12–19 — all concrete)

Items 1–11 carry over from the second-platform playbook (ship-don't-pull, ship
every bind-mount, pg18 volume path, `pg_dump ≥ server`, one deploy path,
migrations via CI only, rate-limit on real client IP, fail-open on login,
monitor from outside, runtime-not-build config, backups before decommission).
**New, paid-for during the WHK migration:**

12. **Container healthcheck must hit a host that's in `AllowedHosts`.** ASP.NET
    Core Host Filtering returns **400 "Invalid Hostname"** for any `Host` not in
    the allow-list. WHK's probe hit `127.0.0.1`, which wasn't listed → a healthy
    backend was marked **unhealthy** and the deploy health-gate failed. **Probe
    `localhost`** (which was allow-listed), not the bare IP. And **add every
    public host — especially the API host — to `AllowedHosts` *before* cutover**,
    or the browser's API calls all 400. (WHK's `api.woodenhouseskenya.com` was
    missing and had to be added.)

13. **Behind a TLS-terminating proxy, app-level HTTPS redirect is a no-op if no
    HTTPS port is configured** — but Host Filtering runs *first* and will 400
    your probe regardless. Don't assume "it's the redirect"; check the actual
    status code from inside the container.

14. **`set -Eeuo pipefail` + a non-local assignment from a failing pipe aborts
    the whole script SILENTLY, before the first log line.** A `grep` that finds
    nothing exits 1; `VAR="$(grep … | …)"` then kills the script under `set -e`
    with **zero output**. Make optional-var reads tolerant:
    `VAR="$(grep … || true)"`. (This produced a bare `exit 1` with an empty log
    on the WHK deploy.)

15. **`npm audit` (or any external-advisory check) must NOT gate deploys.** It's
    non-deterministic — an advisory published overnight fails a deploy of code
    nobody touched (brace-expansion GHSA-mh99-v99m-4gvg did exactly this to WHK).
    **Remediate transitive vulns via lockfile `overrides`** (deterministic), and
    run auditing in a **decoupled** workflow that can't halt a deploy.

16. **Verify TLS on the box *before* flipping DNS.** DNS-01 issues certs without
    the domain pointing at the box; `curl --resolve host:443:127.0.0.1` proves
    valid cert + correct upstream while you're still safely behind the old origin.

17. **The migration-window data gap.** Anything written to the source *between*
    the dump and the cutover lives **only on the source**. Suspend source writes,
    or diff source-vs-target row counts (and newest-timestamp per accumulating
    table) before you decommission. For money this is mandatory, not optional.

18. **Adding a site to the shared Caddy without touching the neighbour:** the
    Caddyfile is a **single file** (`/opt/shulehq/Caddyfile`, no `sites/` dir).
    **Inline** the DNS token in the new block and do a **graceful
    `docker exec sms-caddy caddy reload`** — this beats adding a `CF_API_TOKEN_*`
    env var, which would require **recreating the neighbour's container** (a blip
    for paying clients). Always: **back up → append a fenced block →
    `caddy validate` → reload → neighbour-health-check before AND after.**

19. **Cloudflare proxied records flip in seconds** (no client TTL wait, because
    clients terminate at CF which re-resolves the origin) — **but CF SSL mode
    must be Full(strict)** or CF won't trust the origin's Let's Encrypt cert and
    you'll serve 525/526. Match the mode ShuleHQ/WHK already use.

---

## 7. Backups for WIIF (financial data is sacred)

- **Preferred:** parameterise the existing nightly backup to also dump the `wiif`
  database with its own artifact + retention + per-part `sha256`, and **verify
  TABLE DATA exists before recording success**.
- **Encrypt** the financial dump at rest; push offsite (Cloudflare R2 or the
  existing offsite pull) so "offsite" doesn't depend on a workstation being awake.
- **Restore-drill WIIF before real money flows**, and log it in a `RESTORE_DRILL_LOG.md`.
- Consider **point-in-time recovery** (WAL archiving) for the ledger — for money,
  "restore to last night" may not be good enough; "restore to 12:04:31" might be.
- Add the WIIF artifact to the watchdog's daily freshness check + paging.

---

## 8. Definition of done (WIIF)

- [ ] Live on Contabo; data verified row-for-row against source **and** the
      migration-window delta checked
- [ ] Host/wildcard TLS valid; monitored (edge **and** origin cert)
- [ ] Hard resource caps on every container; **ShuleHQ *and* WHK** health
      unaffected under WIIF load (proven with a load test)
- [ ] **Cross-tenant isolation proven** (RLS denies another tenant's money)
- [ ] **Webhook idempotency proven** with a duplicate/replayed delivery
- [ ] **Fail-closed-on-money proven** (an unverifiable payment is not marked complete)
- [ ] **Daily reconciliation** job green; mismatch paging tested
- [ ] Sandbox↔prod key separation; secrets gitignored, rotation scheduled
- [ ] Immutable financial audit log in place
- [ ] Automated **encrypted** backup fired unattended, restore-verified, offsite
- [ ] External watchdog covers WIIF endpoints incl. webhook callback; paging tested
- [ ] Source decommissioned only after burn-in + final archival dump
- [ ] Tagged release; ops docs written

---

## 9. Quick reference — shared infra facts (box now hosts THREE platforms)

```
VPS:            94.72.102.13  (deploy user "deploy", /opt/<app>)
Tenants:        shulehq (/opt/shulehq) · woodenhouses (/opt/woodenhouses) · wiif (/opt/wiif)
SSH:            ~/.ssh/shulehq_admin_key (admin);  per-platform CI key in GitHub secrets
Edge:           Caddy "sms-caddy", single Caddyfile /opt/shulehq/Caddyfile (no sites/ dir)
                serves *.shulehq.co.ke + woodenhouseskenya.com; TLS via Cloudflare DNS-01
Postgres:       18, shared "sms-postgres" — DBs: shulehq, woodenhouses (+ add wiif)
                superuser role is "shulehq" (POSTGRES_USER), NOT "postgres"
Redis:          shared "sms-redis" — logical DBs: /0 shulehq, /1 whk, (/2 wiif)
Networks:       whk-edge-net/whk-db-net exist; add wiif-edge-net/wiif-db-net
Deploy:         build in CI -> docker save -> ship -> docker load -> compose up (never pull on box)
Cutover:        DNS-01 pre-issue -> curl --resolve verify on box -> flip ONLY app A/CNAME
                (never MX/mail/cpanel/SPF) -> save DNS rollback -> verify from outside
Monitoring:     GitHub Actions watchdog (external); ntfy paging; neighbour checks both tenants
Money rule:     reads may degrade; financial WRITES are correct or refused (fail CLOSED)
Never:          pull private images on box · docker cp migrations · float for money ·
                unverified webhooks · gate deploys on npm audit · touch a neighbour's
                container/DB/network · probe 127.0.0.1 when only localhost is allow-listed
```
