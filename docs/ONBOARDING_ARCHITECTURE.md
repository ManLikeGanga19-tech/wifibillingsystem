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
| Approval bar | **A verified settlement account** — their own M-Pesa paybill **or** bank account |
| Proving they own it | **Micro-transfer** — we send a few shillings with a random reference; they read it back |

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

**What opens the gate: a verified settlement account.** See §3b.

---

## 3b. Settlement account — the thing that opens the money gate

### The insight

The ISP's paybill is **not a collection account**. Customers never pay it. It is a
**settlement destination + KYC proof**, and that makes it an unusually good
approval bar:

> To be issued a paybill (or a business bank account), Safaricom/the bank already
> ran full KYC — business registration, directors, the lot.
> **We inherit their KYC for free.** A shell company cannot produce one.

```
Customer  ->  [DANAMO paybill]  ->  wallet ledger (attributed)  ->  [ISP's paybill/bank]
                 COLLECTION            CUSTODY + our fees              SETTLEMENT
```

### Proving they own it: micro-transfer

Anyone can type `123456`. So we prove control the way banks do:

1. ISP enters their paybill (or bank account).
2. We send a **small B2B/Pesalink payment with a random reference** (e.g. `WOS-4K2P`).
3. They read their own statement and type the reference back.
4. Correct → **settlement verified** → the money gate opens.

Automated, self-serve, cannot be faked, and costs a few shillings + one B2B fee
per ISP — a rounding error against the AML risk it retires. Max 3 attempts, then
a fresh transfer is required (also the abuse/cost control).

> ⚠️ **Depends on an unknown:** does M-Pesa B2B expose an `AccountReference` /
> `Remarks` that the *recipient* can actually see on their statement? If not, we
> fall back to a **random amount** (weaker — far fewer possibilities — so it would
> need tighter attempt limits). **This has been added to the tariff RFI.**

### Model changes

- `Operator`: `settlement_method` (paybill | bank), `settlement_paybill`,
  `settlement_name`, existing `payout_bank_*`, plus `settlement_verified_at`,
  `verification_ref`, `verification_attempts`, `verification_sent_at`.
- `Payout.Method`: add **`paybill`** (B2B) alongside `mpesa` (B2C) and `bank`.
- **Delete the vestigial per-ISP Daraja credentials** (`daraja_consumer_key`,
  `daraja_consumer_secret`, `mpesa_passkey`, `has_mpesa_credentials`). They imply
  per-ISP *collection*, which is not the model and is actively misleading —
  `DarajaClient` already ignores them and always uses Danamo's paybill.

### 🔴 Live bug this exposes — fix it with this work

`pppoe/views.py` tells a suspended broadband customer to pay
**`operator.mpesa_shortcode`** — the *ISP's own* paybill. But C2B confirmations
only ever arrive at **Danamo's** shortcode. So today:

- **ISP shortcode set** → the customer pays the ISP directly; Danamo never sees
  it; the client **stays suspended forever** and the money bypasses the ledger.
- **Shortcode blank** → the customer is shown **no paybill at all**.

The page must show **Danamo's C2B paybill + the client's globally-unique
`account_number`** — exactly what the C2B matcher is built to receive.

### The onboarding pop-up is a trust conversation, not a form

The hardest sentence you will ever say to an ISP is *"your customers' money lands
in my account, not yours."* This modal is where that is won or lost. It must state:

- **Why** — one paybill = one M-Pesa integration, one reconciliation, and **we
  absorb every transaction cost** (they would otherwise pay Safaricom themselves)
- **Where their money is** — held in custody, attributed to them in a **live
  ledger they can see**
- **When they get it** — settled to their own paybill on request
- **What is still locked** — payments stay off until their paybill is verified

Behaviour: shown on first console login; **dismissible** (they can still explore
and configure), but a **pinned setup card** remains and the **money gate stays
shut** until settlement is verified.

### Recommended: verification auto-opens the gate

Once settlement is verified, the KYC question is already answered (Safaricom/the
bank answered it). So **verified settlement should auto-activate** the ISP —
money on, trial starts. That gives true self-serve activation in minutes and beats
Centipid's "live in 24 hours" outright.

Danamo keeps: instant suspend at any time, the full audit trail, and a platform
setting to force manual review (default **off**; flip it on for flagged signups).

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

**B2 — Settlement & KYC** *(this is what opens the gate)*
1. Settlement fields on `Operator`; `Payout.Method.PAYBILL` (B2B)
2. Micro-transfer verification: send, confirm, attempt-limit
3. Auto-activate on verification (with a force-manual-review setting)
4. Onboarding modal + pinned setup card
5. **Fix the suspended-notice bug** — show Danamo's paybill + the client's account number
6. **Delete the vestigial per-ISP Daraja credentials**

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

- [x] ~~What does approval require?~~ → **a verified settlement account** (§3b)
- [ ] **Does M-Pesa B2B show the recipient a reference we set?** Decides whether
      micro-transfer verification uses a random *reference* (strong) or a random
      *amount* (weak). **Added to [TARIFF_INFORMATION_REQUEST.md](TARIFF_INFORMATION_REQUEST.md).**
- [ ] **B2B tariff** — new payout rail, new cost we absorb. Also in the RFI.
- [ ] ToS + Privacy text — Daniel to supply/approve
- [ ] Production email transport (SES/SendGrid/SMTP) — dev is console-only today
- [ ] Rate-limit thresholds (starting proposal: 3 codes/email/hour, 10/IP/hour)
- [ ] Referral-source options for "how did you hear about us"
