# Payment Integrity — never lose or misattribute a shilling

Design agreed with Daniel 2026-07-11. **No code yet.**

Danamo is an aggregator: **all** customer money lands in the WIFI.OS account and is
attributed to the right ISP in a ledger, then settled to that ISP's own
paybill/bank later. The model is standard (Stripe Connect, Paystack, Flutterwave
all work this way). The idea is simple. **One part of the execution is not:**

> *"strictly mapped to the right ISP without making any mistake"* — Daniel

This document is how we earn that sentence.

---

## How each rail attributes money

**Hotspot (STK push) — misattribution is mathematically impossible.**
*We* initiate the payment. The `Transaction` row — with its operator and plan — is
written **before a single shilling moves**, and the callback returns the
`CheckoutRequestID` we issued. The customer never types anything. Attribution is
decided before the money exists.

**Broadband (C2B paybill) — the only real risk.**
Here the **customer** initiates, and the single link between their money and their
ISP is **the account number they type** (`HOME10432`). It is globally unique across
every ISP (DB-enforced), so two ISPs can never collide. But a fat-fingered digit
means money arrives at our paybill belonging to **nobody**.

That is the entire problem. We attack it in three layers.

---

## Layer 1 — Prevent (the biggest win; mostly free)

### 1a. C2B Validation: reject the typo before the money moves

Today we implement only Safaricom's **Confirmation** callback — we are told about
money *after* it has been taken. C2B also supports a **Validation** callback
*before* the payment is accepted: Safaricom hands us the account number and we may
**reject it**.

```
Customer types HOME1O432 (typo)
  -> Safaricom asks us: is this account valid?
  -> we answer NO
  -> customer sees "invalid account number" AT THE TILL
  -> their money never leaves them
```

**No orphan. No ticket. No cut-off customer.** This converts most of the problem
into nothing at all.

> **Go-live dependency:** Safaricom must switch on **External Validation** for the
> shortcode. Until they do, the Validation URL is never called and we silently fall
> back to today's behaviour — so this must be confirmed, not assumed.

### 1b. Canonicalise before declaring anything unmatched

Account numbers are a slug prefix + digits (`HOME10432`). Before calling a payment
unmatched, normalise the reference and retry:

- trim whitespace, strip separators, uppercase
- try the classic human confusions: **O↔0, I↔1, S↔5, B↔8**

This silently rescues most typos at zero cost, in both the Validation and the
Confirmation path.

---

## Layer 2 — Auto-recover (make the human's job 5 seconds, not 5 minutes)

When money *does* land orphaned, never show a raw row. Show **ranked suspects with
their reasons**:

| Signal | Strength | Why |
|---|---|---|
| Payer MSISDN matches a client's phone | **very strong** | that is *their* M-Pesa line |
| Account number within edit distance ≤2 | **strong** | catches the typo directly |
| Amount equals a client's plan price or exact arrears | **strong** | corroboration |
| Client is currently suspended / overdue | moderate | they are the one who would be paying |

Combined into a confidence score with a human-readable justification:

> **Homelink → John Doe (HOME10432) — 96%**
> *phone matches exactly · account off by one character · amount equals his outstanding balance*

**Suggestions only. Money never moves without a person clicking.** (Decided: a
false positive silently puts real cash in the *wrong* ISP's wallet, which is worse
than a short delay. We can revisit auto-match once we have real-world match-rate
data.)

---

## Layer 3 — Resolve (the Unmatched Payments queue)

A first-class screen in Platform Control. Orphaned money is a **liability**, so
every row shows its **age** and escalates: **>24h warn, >72h critical**.

### Actions — platform **owner** only

Money moves here, so `platform_support` may look and never touch.

| Action | What it does |
|---|---|
| **Match to client** | Credits exactly as if C2B had matched: settles the invoice, restores their service |
| **Match to ISP only** | Credits the wallet when there is no client record yet |
| **Refund** | The money was never ours (they paid the wrong paybill). We are obliged to return it — B2C to the payer, cost absorbed |
| **Park** | Genuinely ambiguous: note it, leave it. Still ages |

### The three rails that make this enterprise rather than a button

1. **Idempotent** — the payment's status transition *is* the lock
   (`UNMATCHED → MATCHED/REFUNDED/PARKED`). It cannot be double-credited, even by
   two admins clicking at the same moment.
2. **Reversible** — a *wrong* resolution is worse than an orphan, because now real
   money sits in the wrong ISP's wallet. Resolutions can be reversed with a
   compensating ledger entry, fully audited.
3. **Confirm in words, not with an OK button** —
   *"Credit KES 2,000 to Homelink → John Doe. This settles invoice #441 and
   restores his service."*

Every action writes to the existing audit trail (actor, reason, before/after), so
it surfaces in Governance like everything else.

### The ISP-ticket workflow (what Daniel actually asked for)

> ISP: *"John paid 2,000 on the 5th and he's still cut off."*

Search unmatched payments by **payer phone**, **amount**, **date**, or **TransID** →
see the suspects → resolve. Seconds, from the platform console, without ever
entering the ISP's own dashboard.

---

## Model & API sketch

**`C2BPayment`** gains: `resolution_type` (matched_client | matched_operator |
refunded | parked), `resolved_by`, `resolved_at`, `resolution_note`, `reversed_by`,
`reversed_at`. Status extends to `REFUNDED` / `PARKED`.

```
GET  /platform/unmatched/                 queue: age, value, top suggestion
GET  /platform/unmatched/<id>/suggestions/ ranked candidates + reasons
POST /platform/unmatched/<id>/resolve/    {client_id | operator_id, note}
POST /platform/unmatched/<id>/refund/     {note}
POST /platform/unmatched/<id>/park/       {note}
POST /platform/unmatched/<id>/reverse/    {note}   <- undo a wrong resolution
```

All mutations: **`IsPlatformOwner`**.

---

## Build order

1. **Canonicalisation** at match time (cheap, immediate win, no dependencies)
2. **C2B Validation endpoint** + Safaricom External Validation request
3. **Suggestion engine** (fuzzy account, phone, amount, status signals)
4. **Resolution queue** — API + Platform Control screen, with reversal
5. **Ageing + alerts** wired into the Ops board (already counts unmatched today)
6. Tests: idempotency under concurrent resolve · reversal restores the ledger ·
   a resolved payment cannot be re-resolved · suggestions never cross tenants
   incorrectly

## Open

- [ ] Safaricom: confirm **External Validation** can be enabled on our shortcode
      (added to the tariff RFI / go-live checklist)
- [ ] Refund rail: B2C back to the payer — confirm the tariff (we absorb it)
