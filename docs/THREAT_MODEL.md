# Threat model

Written before staging, by the people who built it. It is not a substitute for a
security team — it is what you hand them on day one so they start from what we already
know instead of rediscovering it.

The framing throughout: **what does an attacker actually want?** Not "is this endpoint
authenticated". They want the money, and there are exactly four ways to it.

---

## What we are protecting

| Asset | Why it is worth stealing | Where it lives |
|---|---|---|
| **The float** | Every ISP's customer payments sit in Danamo's M-Pesa account before settlement. This is the prize. | M-Pesa; the ledger attributes it |
| **The payout destination** | Change it and the next withdrawal goes to the attacker. Cheaper than stealing money — you make us send it. | `Operator.settlement_*` |
| **Daraja credentials** | Impersonate the platform to Safaricom. | env vars only, never in code |
| **`FIELD_ENCRYPTION_KEY`** | Decrypts every router password and TOTP seed. | env var; losing it is unrecoverable |
| **Customer PII** | Phone numbers, payment history, MACs for every ISP's subscribers. A Data Protection Act breach. | Postgres |
| **Router credentials** | Control of an ISP's whole network. | Postgres, Fernet-encrypted |

## Who is attacking

1. **Opportunistic scanners** — constant, automated, not targeting us. Default creds, exposed Postgres, known CVEs.
2. **A fraudulent ISP** — signs up legitimately, then tries to reach *other* tenants' data or money. **The one we design hardest against**, because they are inside the front door by design.
3. **An attacker inside one ISP's console** — phished an owner's password. Wants to redirect the payouts.
4. **A malicious or compromised insider (us)** — a stolen platform account is the highest-value target on the system: every ISP's money is visible from Platform Control.
5. **A customer of an ISP** — wants free wifi. Low value, high volume.

---

## The four paths to the money, and what stands in each

### 1. Redirect an ISP's payouts

*Change where we settle, then wait.* This is the cheapest attack: you never touch the
money, you make us send it to you.

- Only the ISP **owner** may set a payout destination (`CanManageMoney`).
- Changing an existing one needs a **second factor**: TOTP if enrolled, otherwise a code
  emailed to the owner's **login address** — deliberately *not* `contact_email`, which is
  editable in Settings, so an attacker would simply change it and post themselves the code.
- A completed change **re-arms first-payout confirmation** and emails a tripwire. Being
  asked and being told are different things.
- **The cap:** a wrong or hijacked destination costs at most **one payout**, because no
  second payout leaves until the confirmation code from the first is read back.

### 2. Withdraw someone else's balance

- Owner-only, `TenantCanTransact`, **and TOTP on every withdrawal**.
- **Never on a borrowed identity.** `CanManageMoney` refuses every write while
  impersonating. This closed a real hole: platform staff could open a grant, enrol *their
  own* authenticator, and empty a tenant's wallet — the second factor satisfied by the
  attacker's phone, which made it decoration.
- A support-driven MFA reset **freezes withdrawals for 24h** and emails the owner.

### 3. Forge a payment

*Tell us money arrived when it did not, then withdraw the credit.*

- The C2B/STK callbacks are the only unauthenticated endpoints that can create money.
  They carry a **shared token in the URL** (`DARAJA_CALLBACK_TOKEN`) and are idempotent
  on `CheckoutRequestID` / `TransID`.
- **Residual risk, stated plainly:** the token is the only thing authenticating Safaricom.
  Anyone who learns it can mint a payment. Mitigations to add before real volume: IP
  allow-listing of Safaricom's ranges at Caddy, and a reconciliation job that flags any
  ledger credit with no matching Daraja query result. *Not built yet.*

### 4. Reach another tenant's data

- Fail-closed tenancy: `acting_tenant()` resolves to **exactly one** operator or refuses.
  There is no "no tenant means show everything" path — that produced a real leak once.
- Tenant staff are pinned to their own operator **regardless of the Host header**, so a
  stolen cookie replayed on another ISP's subdomain crosses nothing.
- Platform staff reach a foreign tenant **only** through a live, time-boxed, audited
  `ImpersonationGrant` — and now cannot move money there at all.
- **Known trap:** a `get_queryset` override that forgets to chain `super()` silently
  drops the operator filter. It has happened once. Any new `TenantModelViewSet` must be
  reviewed for it.

---

## Other exposures, and where they stand

| Attack | Standing |
|---|---|
| Password guessing | Per-IP throttle (10/min) **and** per-account lockout (10 fails → 15 min). Both, because an IP limit falls to a botnet and an account limit falls to password spraying. |
| Account enumeration | Signup, login, and find-console all return **identical** responses for known and unknown addresses. Tested. |
| XSS stealing a session | Auth is an **httpOnly** cookie — JavaScript cannot read it. Strict CSP (`script-src 'self'`, no CDN) at the edge. No `localStorage` anywhere, by rule. |
| CSRF | Cookie auth reintroduced it; double-submit token, enforced only for cookie-authenticated writes. `SameSite=Lax` + same-origin API means we never need `SameSite=None`. |
| Clickjacking | `X-Frame-Options: DENY` + `frame-ancestors 'none'`. |
| Exposed database | No published port in production. Reachable only on the private Docker network. (The dev compose *does* publish 5432 for DBeaver — that must never be copied to a server.) |
| Secrets in the repo | `gitleaks` in CI, blocking. Zero keys in source is a hard rule. |
| Dependency CVEs | `pip-audit`, `npm audit`, Trivy on the image. Advisory until there is someone to triage them. |
| Container escape | Non-root user, `no-new-privileges`, read-only root filesystem on the app containers. |
| DoS | Honestly: **thin.** Caddy will absorb some, throttles cover the expensive endpoints. A determined flood takes the box down. Accepted for a pilot; Cloudflare in front is the answer when it matters. |

---

## What we are NOT protected against — say it out loud

1. **A compromised platform-owner account.** They cannot move an ISP's money directly any
   more, but they can suspend tenants, read every ledger, and reset an MFA device. Real
   mitigation: hardware keys for platform logins, and someday two-person approval on
   payouts. *Not built.*
2. **A forged Daraja callback**, if the token leaks (see path 3).
3. **A malicious dependency.** We pin lockfiles and scan, which catches known-bad, not
   novel-bad.
4. **The box itself.** One VPS. Root on it is game over — and that is an accepted risk of
   the cheap topology, not an oversight. Consequently: SSH keys only, no password auth,
   no root login, firewall to 80/443/22.
5. **Insider access to backups.** The dumps are unencrypted on disk. Encrypt them before
   they go offsite.

---

## The rules that keep it true

These are the things a future engineer will break without meaning to:

1. **Never bypass `acting_tenant()`.** No raw `Model.objects.all()` in a tenant view.
2. **Always chain `super().get_queryset()`.**
3. **No secrets in code.** Ever. `prod.py` refuses to boot without them; do not add a fallback.
4. **No browser storage.** The server owns the session.
5. **Money paths need a second factor and an audit line.** If you add one, it needs both.
6. **Public endpoints use `PublicAPIView`** — `authentication_classes = []`. A public view
   that still *authenticates* was the CSRF bug on the captive portal.
