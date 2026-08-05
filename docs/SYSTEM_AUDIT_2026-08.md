# System Audit — Tenant Isolation & Production Readiness

**Date:** 2026-08-05
**Scope:** Whole backend (`backend/apps/**`), the four frontends, deploy config, CI/CD.
**Focus, as requested:** cross-tenant data leakage, enterprise-grade correctness, production readiness.

---

## 1. Verdict

**Tenant isolation is structurally sound.** It is enforced by construction — not by
remembering to filter — and the two historical leaks (an unfiltered queryset for platform
admins, and cross-tenant FK assignment) are both closed and pinned by tests.

**I found no way for one ISP to read or write another ISP's data** through the authenticated
API. The findings below are real and worth fixing, but none of them is a tenant-to-tenant
data leak. They are: one missing rate-limit control, one unauthenticated PII lookup,
plaintext credential exposure to a privileged reader, and structural inconsistencies that
are safe today but make a future leak easier to introduce.

**Honest scope limit:** this is a code and configuration audit, not a penetration test. I
did not fuzz endpoints, attempt live exploitation, or test the running staging box. Where I
say "safe", I mean "the code path enforces it and I traced it", not "proven unbreakable".

---

## 2. How isolation actually works (verified)

Worth stating plainly, because the rest of the report depends on it.

| Layer | Mechanism | File |
|---|---|---|
| Resolution | `acting_tenant()` resolves **exactly one** operator, or none. No "all tenants" path exists. | `apps/core/tenancy.py` |
| Guard | `RequireTenant` **fails closed** — no resolved tenant ⇒ 403, never an unfiltered queryset. | `apps/core/permissions.py:34` |
| Query | `TenantScopedMixin.get_queryset()` always `.filter(operator=...)`. | `apps/core/viewsets.py:40` |
| Writes | `perform_create` stamps the operator server-side; the client cannot choose it. | `apps/core/viewsets.py:44` |
| FKs | `TenantPrimaryKeyRelatedField` constrains relation choices to the acting tenant. | `apps/core/serializer_fields.py` |
| Cross-tenant reach | Platform staff need a **live, audited `ImpersonationGrant`**; the header alone is not enough. | `apps/core/tenancy.py` |

**Verified clean:**
- **No plain `PrimaryKeyRelatedField` anywhere** — every writable FK is tenant-scoped. This
  was the confirmed leak in the earlier audit; it is genuinely fixed.
- **No `get_object()` overrides** — object lookup always goes through the filtered queryset,
  so there is no path that fetches by PK outside the tenant filter.
- **No raw SQL / `.raw()` / cursors** — no way to bypass the ORM's scoping.
- **No CORS package** — the same-origin design means no cross-origin cookie exposure.
- **Secrets encrypted at rest**: router password, WireGuard private key, gateway secrets,
  SMTP password, webhook secret, AI provider key (`EncryptedTextField`).
- **No secrets written to logs** (grep across all log calls).
- **C2B payment routing is safe**: `account_number` is globally unique, so a paybill
  payment resolves to exactly one client ⇒ one operator. Non-transacting ISPs' money is
  *held*, not credited (`apps/payments/c2b.py`).
- **Webhooks and the AI assistant** are operator-scoped (`emit_event` filters by operator).

---

## Status — updated 2026-08-05

| Finding | Status |
|---|---|
| F1 — throttling not enforced | ✅ **Fixed** — `DEFAULT_THROTTLE_CLASSES` wired + a `user` rate; pinned by `tests/test_prod_settings.py` |
| F2 — account lookup enumerable | ✅ **Fixed** — tight per-IP throttle + last-4-phone-digits required; identical 404 for wrong account vs wrong phone (no oracle) |
| F3 — bulk credential export | ✅ **Fixed** — passwords opt-in (`?include_credentials=true`), refused on a borrowed identity, and audited. The ISP owner can still take everything (portability preserved) |
| F4 — hand-rolled tenant scoping | ✅ **Fixed** — `SubscriberViewSet` and `ApiTokenViewSet` now inherit the scoping mixin |
| F5 — prod-only config untested | ✅ **Fixed** — `tests/test_prod_settings.py` asserts throttling, cookies, HSTS, proxy header, redirect-exemption and fail-loud secrets against the REAL prod module |
| F6 — import preview username | ⚪ Won't fix — informational; the global check is required for correctness |

The findings below are the original write-up, kept as the record of what was found and why.

---

## 3. Findings

### F1 — `anon` throttle is defined but never enforced (Medium)

`DEFAULT_THROTTLE_RATES` defines `"anon": "60/min"`, but **`DEFAULT_THROTTLE_CLASSES` is
never set**, so DRF applies no default throttle at all. The rate is dead configuration.

- **File:** `backend/config/settings/base.py` (REST_FRAMEWORK block, ~line 126)
- **Effect:** every endpoint that does *not* declare its own `throttle_scope` is
  **completely unrate-limited**. The named scopes (`login`, `stk-push`, `signup`,
  `voucher-redeem`, `device-mgmt`, `device-recover`, `signup-check`) *are* wired correctly
  and do work — this affects everything else.
- **Why it matters:** it reads as protected but isn't. Combined with F2 it enables
  enumeration; more broadly it leaves the API open to cheap scraping/abuse at tenant scale.
- **Fix:** add to `REST_FRAMEWORK`:
  ```python
  "DEFAULT_THROTTLE_CLASSES": [
      "rest_framework.throttling.AnonRateThrottle",
      "rest_framework.throttling.UserRateThrottle",
  ],
  ```
  and add a `"user"` rate alongside `"anon"`. Verify the scoped throttles still pass
  (`tests/test_*` around login/signup) — `ScopedRateThrottle` views override the default.

---

### F2 — Unauthenticated account lookup returns customer PII, unthrottled (Medium)

`account_lookup` is public by design (a suspended customer types their account number to
see their balance and how to pay). It returns **full name, plan, monthly price, balance,
and status**.

- **File:** `backend/apps/pppoe/views.py:387–419`
- **Correctly scoped:** it *is* tenant-scoped (operator from subdomain or `?router=`), so it
  cannot cross tenants. **This is not a tenant leak.**
- **The problem:** no authentication *and* no throttle (see F1). Account numbers are short
  and structured (`HOME` + 5 chars), so they are brute-forceable. An attacker can enumerate
  one ISP's customer list — names and outstanding balances.
- **Fix (do both):**
  1. Give it an explicit `throttle_scope` (e.g. `"account-lookup": "10/min"`), which works
     even before F1 is fixed.
  2. Consider requiring a second factor the real customer has — e.g. the last 4 digits of
     their phone — before returning the name and balance. Returning only
     "account exists, balance due" without the name would also close most of the value.

---

### F3 — PPPoE passwords are stored and exposed in plaintext (Low–Medium, by design but under-controlled)

`Client.pppoe_password` is a plain `CharField`, and is returned by the client API, shown in
the Credentials dialog, and included in the CSV export.

- **Files:** `backend/apps/pppoe/models.py:145`, `apps/pppoe/serializers.py`,
  `apps/pppoe/porting.py` (`CLIENT_CSV_COLUMNS`)
- **Why it's plaintext:** PPPoE/CHAP requires a retrievable secret, and RouterOS stores it
  in plaintext anyway. The installer genuinely needs to read it. **This is a legitimate
  design decision**, unlike an application password.
- **The gap:** it is not *treated* as sensitive. Specifically:
  - The **CSV export includes every client's password** in one download, and the export is
    a `GET` — so it passes `ReadOnlyForSupport` (safe methods allowed). **Platform support
    staff holding an impersonation grant can download an ISP's entire credential set.**
  - I found **no audit entry** for the export or for viewing credentials.
- **Fix:**
  1. Write an `audit()` entry for the CSV export and for credential reveal — so a bulk
     credential read is at least *recorded*. (Impersonation is already audited; this makes
     the specific action visible.)
  2. Consider omitting `pppoe_password` from the CSV by default, with an explicit
     `?include_credentials=true` that is owner-only and separately audited.
  3. Consider gating the export behind `CanManageMoney`-style owner-only permission rather
     than any read access.

---

### F4 — Two viewsets bypass the scoping mixin (Low — safe today, fragile tomorrow)

Two viewsets filter by tenant *manually* instead of inheriting `TenantScopedMixin`:

| Viewset | File | Pattern |
|---|---|---|
| `SubscriberViewSet` | `apps/accounts/views.py:121` | `Subscriber.objects.filter(operator=acting_tenant(request))` |
| `ApiTokenViewSet` | `apps/developer/views.py:34` | `ApiToken.objects.filter(operator=self.get_operator(), ...)` |

- **Are they leaking? No.** Both filter by operator, and both carry `RequireTenant`, which
  fails closed before the queryset runs. If `acting_tenant()` somehow returned `None`,
  `filter(operator=None)` matches nothing (the FK is non-null), so it fails safe.
- **Why it's still a finding:** the mixin raises `PermissionDenied` on a missing tenant
  (defence in depth); these rely on the permission class alone. More importantly, they
  establish a "hand-rolled scoping" pattern — and the one class of bug this system has
  already shipped twice is *a queryset that forgot to filter*. Consistency is the control.
- **Fix:** have both inherit `TenantScopedMixin` (or `TenantReadOnlyViewSet`) and chain
  `super().get_queryset()`, keeping their annotations/filters on top.

---

### F5 — Deploy-time configuration is only exercised under test settings (Process — High value)

**This one caused a real outage today**, so it is a finding about the *process*, not a line
of code.

The health check I added passed locally and in CI, then took the staging API down on the
first deploy. Two prod-only behaviours were never exercised:

1. `ALLOWED_HOSTS` — test settings use `["*"]`, so a `DisallowedHost` failure is impossible
   to reproduce in the suite.
2. `SECURE_SSL_REDIRECT` — off in tests, so the 301-on-probe failure was invisible.

- **Fixed for this instance:** `backend/tests/test_prod_health_check.py` now asserts the
  invariants against the **real** `config.settings.prod` module.
- **The class of bug remains:** anything that only behaves differently under prod settings
  (cookie domains, HSTS, `SECURE_*`, `CSRF_TRUSTED_ORIGINS`, proxy headers) has the same
  blind spot.
- **Fix:** extend the prod-settings test approach — a small suite that imports
  `config.settings.prod` and asserts the deploy-critical invariants. Consider a CI smoke
  step that boots the API with prod settings behind the real Caddy config and curls
  `/api/v1/health/` before the deploy job runs.

---

### F6 — Import preview reveals that a username exists on another tenant (Informational)

`preview_import` checks `Client.objects.filter(pppoe_username__in=...)` **globally** (not
per-tenant) to flag `already_managed`.

- **File:** `backend/apps/pppoe/porting.py` (`preview_import`)
- **Effect:** if tenant A imports from their router and a username happens to be managed by
  tenant B, A sees `already_managed: true`. No name, plan, or contact data is exposed —
  only the existence of that username, which A already reads off their own router.
- **Why the global check is correct:** `pppoe_username` is globally unique, so the check
  must be global or the import would fail later on an integrity error.
- **Assessment:** negligible. Documented so a future reader doesn't "fix" it into a bug.

---

## 4. Production readiness

### Strong
- **Prod settings fail loudly**: missing `DJANGO_SECRET_KEY` / `FIELD_ENCRYPTION_KEY` /
  `DATABASE_URL` / `DARAJA_CALLBACK_TOKEN` refuses to boot rather than silently downgrading.
- **Transport hardening**: HSTS 2y + preload + subdomains, `SECURE_SSL_REDIRECT`,
  nosniff, referrer policy, secure + httpOnly cookies, `SameSite=Lax`, CSRF double-submit.
- **No browser storage** anywhere — the server owns the session (a hard project rule, and it
  is genuinely honoured in the client code).
- **Database is not published** to the host; Redis is password-protected.
- **Containers**: `read_only` root FS, `no-new-privileges`, non-root user, tmpfs for the
  writable paths.
- **CI gates**: ruff, full pytest, missing-migration check, OpenAPI `--fail-on-warn`,
  `check --deploy`, image build + Trivy scan, and a **blocking** gitleaks secret scan.
  The deploy job only runs after all of them pass, and now `--wait`s on the health check.
- **Zero-downtime rollout** is in place (Caddy hold-and-retry + container health check).

### Gaps worth closing
1. **F1** (throttling) — the most impactful quick win.
2. **Backups are untested.** `docs/DEPLOYMENT.md` says a backup you have never restored is
   not a backup. The nightly `pg_dump` runs; **do a restore drill before real money flows.**
3. **No error tracking / alerting.** Sentry is referenced as a hook point but not wired. In
   production you will learn about 500s from an ISP phoning you.
4. **`pip-audit` / `npm audit` are `continue-on-error`.** Correct for now (no team to triage
   at 2am), but make them blocking before you onboard paying ISPs.
5. **Single VPS, co-tenanted** with two unrelated projects. Fine for staging and the pilot;
   plan the move to a dedicated box before production traffic, as already intended.

---

## 5. Suggested fix order

| # | Finding | Effort | Why this order |
|---|---|---|---|
| 1 | **F1** — enable `DEFAULT_THROTTLE_CLASSES` | ~15 min | Dead config that reads as protection; also mitigates F2 |
| 2 | **F2** — throttle + harden `account_lookup` | ~1 h | Unauthenticated customer PII |
| 3 | **F3** — audit + gate credential export | ~1–2 h | Bulk credential read is currently silent |
| 4 | **F5** — prod-settings test coverage | ~2 h | Prevents a repeat of today's outage class |
| 5 | **F4** — fold the two viewsets into the mixin | ~30 min | Consistency; removes the pattern that caused past leaks |
| 6 | Backup restore drill | ~1 h | Must happen before real money |
| 7 | Wire Sentry | ~1 h | Production visibility |

---

## 6. What I checked

Backend: tenancy middleware and `acting_tenant` resolution; `RequireTenant` and every
permission class; every `get_queryset` override (18) for `super()` chaining; every writable
serializer FK; `get_object` overrides; raw SQL; all `AllowAny` / no-auth endpoints; the
public portal surface; C2B payment matching and the money gate; unmatched-payment
resolution; platform-only endpoints and their gating; impersonation grants; webhook
dispatch; the AI assistant's data path; encrypted-field coverage; secret logging; Celery
task scoping; throttle configuration.

Config/infra: `base.py` / `prod.py` / `test.py` settings; `docker-compose.prod.yml`;
`Caddyfile`; `.github/workflows/ci.yml`.

Frontends: API client auth/session handling, no-browser-storage rule, tenant switching.

**Not covered:** live penetration testing, dependency CVE triage, load/DoS behaviour,
RouterOS-side security, and the marketing site's content.
