# ISP Onboarding & Website — Architecture

Foundation for the public marketing site and the 5-step ISP signup. Agreed with
Daniel 2026-07-11. **No code yet — this is what we build against.**

---

## Decisions locked

| Decision | Choice |
|---|---|
| After signup | **Explore now, money gated** — console opens immediately; payments & withdrawals stay off until approved |
| Website stack | **Astro + React islands** (static HTML for SEO, React for the wizard) |
| Step-4 "billing" field | **Billing currency, not company** — implicit KSh (Kenya-only), so it is *not a field at all* |
| ISP roles | **Owner only.** Manager + Support are retired from the ISP side for now |
| Login identity | **Phone OR email** — either works |

---

## 1. The core problem: multi-step state without browser storage

A 5-step wizard must remember steps 1–4 while you are on step 5. The obvious
place is `localStorage` — which [the no-browser-storage rule](#) forbids, and
rightly: a half-finished signup rotting in a browser across a deploy is exactly
the stale-state trap that already bit us twice.

**So the draft is a server resource**, referenced by an httpOnly cookie — the same
pattern as auth. The client stores **nothing** and simply asks:
*"which step am I on, and what do you already know about me?"*

Consequences, all good:
- Refresh-safe, back-button-safe, close-the-laptop-safe.
- Abandoned drafts expire (48h) and are swept. Nothing rots.
- A deploy mid-signup cannot corrupt anyone's state.

### `SignupApplication`

| Field | Step | Notes |
|---|---|---|
| `id` (uuid), `created_at`, `expires_at`, `ip` | — | 48h lifetime |
| `full_name`, `email` | 1 | |
| `code_hash`, `code_expires_at`, `attempts`, `resends`, `last_sent_at` | 2 | **hash the code — never store it in plaintext** |
| `email_verified_at` | 2 | the gate to step 3 |
| `company_name`, `slug` | 3 | soft-reserved on the draft |
| `county`, `phone`, `referral_source` | 4 | currency is implicit KSh |
| `tos_version`, `tos_accepted_at` | 5 | **legal record — version matters** |
| `status` | — | `draft → verified → submitted` |

On completion it mints the real `Operator` (PENDING) + owner `User`, then is consumed.

### API

```
POST /signup/start/      {name, email}            -> sets httpOnly signup cookie, emails a code
POST /signup/verify/     {code}                   -> marks verified
POST /signup/resend/                               -> cooldown-gated
GET  /signup/state/                                -> {step, known_fields}  <- how a refresh resumes
GET  /signup/slug-check/ ?slug=acme                -> {available, suggestion}
POST /signup/company/    {company_name, slug}
POST /signup/details/    {county, phone, referral}
POST /signup/complete/   {password, accept_tos}   -> Operator(PENDING) + Owner user, cookie cleared
```

---

## 2. This is our first anonymous write endpoint — build it defensively

Everything else in the system is behind auth. This is not. Treat it accordingly:

| Threat | Defence |
|---|---|
| **Email bombing** a victim's address | per-email + per-IP rate limit, 60s resend cooldown, daily cap |
| **Code brute force** (6 digits = 1M) | max 5 attempts then burn the draft; 10–15 min expiry |
| **Account enumeration** | "send code" must **never** reveal whether an email exists. Always answer *"if that address is valid, we've sent a code."* If it IS registered, email them *"you already have an account — sign in"* instead of a code. Same rule for phone at step 4. |
| **Slug/name race** | soft-hold on the draft, but the **DB unique constraint is the referee**; on conflict, bounce cleanly back to step 3 |
| **Worthless ToS** | record version + timestamp + IP, or the checkbox means nothing legally |

### New uniqueness constraints required

- `Operator.name` — **case-insensitive unique** (Daniel: "no duplicate slugs/company name"). Not unique today.
- `User.email` — **case-insensitive unique**. Required before email can be a login identity.

---

## 3. The money gate (the biggest change)

Today `TenantIsOperational` blocks any non-`active` tenant from the console
outright. That single gate must become **two independent ones**:

- **`TenantIsOperational`** — may you *use* the console?
- **`TenantCanTransact`** *(new)* — may money move?

| Capability | Pending | Approved |
|---|---|---|
| Console access | ✅ | ✅ |
| Routers: add, setup script, test connection, re-sync | ✅ | ✅ |
| Plans, towers/APs, branding, settings | ✅ | ✅ |
| Wallet (view) | ✅ | ✅ |
| **Collect payments** (STK, C2B) | ❌ | ✅ |
| **Redeem vouchers** | ❌ | ✅ |
| **Provision live customers** (hotspot session, PPPoE) | ❌ | ✅ |
| **Withdraw** | ❌ | ✅ |
| Free-trial clock | not started | **starts at approval** |

Three consequences to build, not just assert:

1. **A pending ISP's captive portal is NOT live.** Its plans must not be
   purchasable. Otherwise a real customer pays real money to an unvetted ISP
   *through Danamo's paybill* — precisely the KYC/AML risk this gate exists for.
2. **The console needs an honest banner** — *"You're set up. Payments switch on
   once we verify your business."* — plus a visible checklist of what we still
   need from them.
3. The trial already starts in `approve()`, which now correctly means *"starts
   when they can actually earn"* rather than *"when they filled in a form"*.
   That semantic is already right in the code.

> **Open question for Daniel:** what do you actually need to approve an ISP?
> (Business registration? ID? Their own paybill? A call?) That answer *is* the
> checklist in point 2, and it is the last unknown in this design.

---

## 4. Roles & login

**ISP side = Owner only.** `TENANT_MANAGER` and `TENANT_SUPPORT` are retired from
the ISP experience (multi-staff gets designed properly later). Platform roles
(`platform_owner`, `platform_support`) are unchanged — `platform_support` is still
read-only, so `ReadOnlyForSupport` stays.

*Migration note:* the enum members stay in the DB (removing them would break
existing rows); we simply stop issuing them, drop them from the UI, and update
`seed_dev`.

**Login accepts phone OR email.** Input that looks like an email resolves by
email; otherwise it is normalised as a Kenyan MSISDN. Requires the
case-insensitive unique `User.email` above.

---

## 5. The website

SEO matters — ISPs will find this via Google, and a Vite SPA renders an empty
`<div>` to a crawler. That is the one place our current stack is the wrong tool,
hence **Astro**: static HTML for the marketing pages (fast on poor connections,
near-zero JS), with the signup wizard as a **React island** reusing our existing
design system.

### Domains

```
www.wifios.co.ke      -> marketing + /get-started (the wizard)
admin.wifios.co.ke    -> Platform Control
{slug}.wifios.co.ke   -> ISP console
```

A happy consequence of cookie auth: cookies scoped to `.wifios.co.ke` mean an ISP
can **sign in on www and land in their console already authenticated** — no
"what's my subdomain?" problem to solve.

### Pages

Home · Pricing (the finance model) · Features · Get Started (wizard) · Sign in ·
**Terms of Service** · **Privacy Policy** · Contact.

> The ToS checkbox in step 5 is legally worthless without real ToS + Privacy
> pages. **Daniel must supply or approve that text** — it is a blocker for launch,
> not for build.

### Design

Same brutalist system as every other surface — Inter / JetBrains Mono / Playfair,
`#E4E3E0` plane, white panels, square `#141414` hairlines. **No new visual
language.** Mobile-first and light on JS: many Kenyan ISPs will land on a phone,
on a poor connection.

---

## 6. Build order

**A — Signup backend**
1. `SignupApplication` model + migration
2. Email verification: code generate/hash/send (`DjangoEmailProvider` already exists; SMTP env vars already wired, console backend in dev)
3. The 7 endpoints above
4. Anti-enumeration + throttles
5. Unique constraints: `Operator.name` (ci), `User.email` (ci)

**B — The money gate**
1. Split `TenantIsOperational`; add `TenantCanTransact`
2. Apply to: STK push, C2B credit, voucher redeem, hotspot/PPPoE provisioning, payout request
3. Portal refuses a pending ISP's plans
4. Console banner + "what we still need" checklist

**C — Roles & login**
1. ISP = Owner only (UI + `seed_dev`)
2. Login accepts phone or email

**D — Website (Astro)**
1. Scaffold, shared design tokens
2. Marketing pages + ToS/Privacy shells
3. The 5-step wizard island (server-driven, storage-free)
4. Sign-in entry point

**E — Tests**
Signup happy path · resume-after-refresh · code expiry/attempt burn · enumeration
resistance · slug race · **the money gate (a pending ISP cannot take a shilling)**.

---

## 7. Open items

- [ ] **What does approval actually require?** (defines the console checklist)
- [ ] ToS + Privacy text — Daniel to supply/approve
- [ ] Production email transport (SES/SendGrid/SMTP) — dev is console-only today
- [ ] Rate-limit thresholds (starting proposal: 3 codes/email/hour, 10/IP/hour)
- [ ] Referral-source options for "how did you hear about us"
