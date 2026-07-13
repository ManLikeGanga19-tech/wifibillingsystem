# Finance refactor — instant settlement for ISPs

**Status:** in progress. Agreed 2026-07-13.

## Why

Today WIFI.OS is an **aggregator**: every shilling a subscriber pays lands on Danamo's
paybill, we attribute it to the ISP in a ledger, and the ISP withdraws later. That is
safe, but it means an ISP waits for their own money.

ISPs want to be paid **instantly**, into **their own** account. So an ISP may now connect
their own payment gateway (M-Pesa via Daraja, Kopo Kopo, Pesapal, …) and subscriber money
goes straight to them, never touching us.

We keep both. That is the whole design.

| | Money goes | We are paid by | ISP withdraws? |
|---|---|---|---|
| **WIFI.OS paybill** (default, zero setup) | to us | withholding 3% at source | yes, from wallet |
| **Own gateway** | to the ISP, instantly | monthly invoice, paid by STK push | no — they already hold it |

Either way, **every sale is recorded identically for revenue**. Only *custody* differs.

The aggregator path is not legacy — it is what lets a brand-new ISP sell on day one, while
their own Daraja shortcode is still weeks away from Safaricom's approval.

---

## THE INVARIANT (the one that matters)

> **An ISP may only ever withdraw money that WIFI.OS is actually holding.**

Today `wallet_balance()` is the sum of *every* ledger entry, and payouts are paid against
it. The moment a **directly-settled** sale writes a credit to that ledger, we would be
showing an ISP a balance of money **we never received — and letting them withdraw it**.

That failure is silent, it happens on *every* direct sale, and it is unbounded. So the
ledger grows a **custody** dimension, independent of revenue:

- `LedgerEntry.settlement`
  - `platform` — the cash is in our account. Counts toward what they can withdraw.
  - `direct` — the cash went to the ISP's own account. Recorded for revenue and for
    computing our fee. **Never withdrawable — we do not have it.**

Two different books over the same events:

| Question | Answer |
|---|---|
| What can this ISP withdraw? | sum of `platform` entries |
| What did this ISP earn? | all sale entries, both settlements |
| What float are we holding? | sum of `platform` entries, all tenants |
| What do we owe ISPs? | sum of `platform` entries, all tenants |

Anything that means *"cash we hold"* must filter on `platform`. Anything that means
*"business done"* must not.

---

## Phases

### Phase 1 — the custody split ✅ first, alone, before anything else
- `LedgerEntry.settlement` + migration backfilling every existing row as `platform`
  (which is the truth: today, all money passes through us).
- `withdrawable_balance()` = platform-only. `request_payout()` reads it and nothing else.
- Audit **every** ledger aggregation in the codebase (there are ~15) and decide, per site,
  whether it means custody or revenue. A missed one is the silent bug.
- Tests that would fail loudly if a direct sale ever became withdrawable.

Nothing else is built until this is true.

### Phase 2 — the platform account (replaces SMS credits)
One **KES balance** per ISP — the thing an ISP owes us, or has prepaid. It may go
**negative**: that is postpaid.

A single signed ledger, in shillings:
- SMS sends debit it in real time (per 160-char segment)
- Commission on **direct** sales, PPPoE per-user fees, base fee — debit as they accrue
- Top-ups (**STK push** to Danamo) credit it
- **Negative balance = what they owe us**

This replaces the integer `SmsCreditEntry` and its wallet-funded purchase, which only
worked because money passed through us. Top-up packages remain (KES, showing an
approximate SMS count). Adds low-balance alerts: threshold + alert phone numbers.

### Phase 3 — gateway registry + M-Pesa (Daraja)
Same shape as the SMS provider registry: catalog → encrypted credentials → one active →
Configure / Use this.

Every adapter does three things, and the third is not optional:
- `charge()` — STK push / card redirect / payment instructions
- `webhook()` — normalize an incoming payment into a `Transaction` (idempotent)
- `verify()` — reconciliation query. **Callbacks get lost.** This is what caused the
  spinning-portal bug, and the fast reconciler is what fixed it.

M-Pesa first: collection method (paybill **or** till), shortcode, consumer key, consumer
secret, passkey. Paybill and till use *different* Daraja transaction types
(`CustomerPayBillOnline` vs `CustomerBuyGoodsOnline`) — silently wrong if confused.

Per-tenant callback URLs, now that each ISP has their own subdomain.

### Phase 4 — invoicing and enforcement
Monthly statement of accrued charges → STK to settle → grace → suspend selling.

**Postpaid means we carry credit risk.** An ISP can collect a month of subscriber money
into their own paybill and simply not pay. Suspension is the only lever and it is blunt,
so an **exposure cap** (auto-suspend past *X* owed) matters more than the monthly cycle.

### Phase 5 — remaining gateways
Kopo Kopo, Pesapal, Paystack, DPO Pay, Bank transfer (manual confirmation).

**Dropped:** PayPal (not a Kenyan rail), Relworx (Uganda).

**Deferred — not built:** "M-Pesa paybill/till *without* API keys". The only way these can
work is an app forwarding M-Pesa SMS off a phone, and **an SMS is trivially forgeable**.
Shipping that without explicit safeguards (sender validation, receipt-code uniqueness,
amount + freshness matching) would put a free-WiFi exploit inside a billing system. It
needs its own decision.

---

## Revenue accuracy

Whatever gateway an ISP picks, the billing system must not fail to produce accurate
revenue. That means every gateway normalizes into the same `Transaction`, with:

- **idempotent** webhooks (a duplicate callback must be a no-op — Safaricom retries)
- a **reconciliation** sweep per gateway, because callbacks are lost in the wild
- the existing **unmatched-payments queue** for money we cannot attribute

A sale is never invented and never lost, regardless of who held the cash.
