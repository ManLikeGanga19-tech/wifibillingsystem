# Transaction Tariff — Request for Information (RFI)

**From:** Danamo Tech Ltd
**Re:** Confirmed tariff schedule for an aggregator Paybill (collections) and ISP disbursements
**Purpose:** We operate a billing platform that **collects customer payments on behalf of
multiple sub-merchants (ISPs) into a single Paybill**, holds them in custody, and
disburses to each ISP. Because Danamo **absorbs all transaction costs** (they are not passed
to ISPs), we need the *exact, current* cost schedule to price our service correctly. Vague
or "approximate" figures are not sufficient for our reconciliation and margin model.

Please complete the tables below with **current, confirmed** figures and indicate the
**effective date** of the schedule quoted.

---

## PART A — Safaricom M-Pesa (Daraja / Paybill)

### A0. Account structure (aggregator / PSP)

We collect for **multiple ISPs** through one shortcode and attribute each payment via the
account reference (BillRefNumber). Please confirm:

1. Is our current shortcode a **Paybill** or **Buy Goods (Till)**? __________
2. Does Safaricom require an **aggregator / Payment Service Provider (PSP) agreement** for
   collecting on behalf of sub-merchants? If so, what is the process and does it change the
   tariff? __________
3. Are there **separate collection (C2B) and disbursement (B2C) shortcodes**, or one? ______
4. What is the **settlement path and timing** — when do collected funds become available to
   us for B2C payout / bank settlement (T+0 real-time, T+1, other)? __________

### A1. Collection — C2B (customer → our Paybill)

The most important figures. Please confirm the charging model first:

- **Who bears the C2B charge?**  ☐ Customer pays the fee (we receive the full amount, $0 cost
  to us)   ☐ Business/merchant pays the fee (we absorb it)   ☐ Configurable per shortcode

If the **business** bears any part of the C2B fee, give the full band table:

| Amount band (KES) | Fee charged to us (KES) | Fee is % or flat? |
|---|---|---|
| 1 – 49 | | |
| 50 – 100 | | |
| 101 – 500 | | |
| 501 – 1,000 | | |
| 1,001 – 1,500 | | |
| 1,501 – 2,500 | | |
| 2,501 – 3,500 | | |
| 3,501 – 5,000 | | |
| 5,001 – 7,500 | | |
| 7,501 – 10,000 | | |
| 10,001 – 15,000 | | |
| 15,001 – 20,000 | | |
| 20,001 – 35,000 | | |
| 35,001 – 50,000 | | |
| 50,001 – 150,000 | | |

- Is there a **maximum fee (cap)** per collection? __________ KES
- Is there a **free threshold** (amount at/below which collection is free to us)? _______ KES

### A2. Disbursement — B2C (our Paybill → an ISP's M-Pesa)

Used when an ISP withdraws their wallet balance to M-Pesa.

| Payout amount band (KES) | Fee charged to us (KES) |
|---|---|
| 1 – 1,000 | |
| 1,001 – 1,500 | |
| 1,501 – 2,500 | |
| 2,501 – 3,500 | |
| 3,501 – 5,000 | |
| 5,001 – 7,500 | |
| 7,501 – 10,000 | |
| 10,001 – 15,000 | |
| 15,001 – 20,000 | |
| 20,001 – 35,000 | |
| 35,001 – 50,000 | |
| 50,001 – 150,000 | |
| 150,001 – 250,000 | |

### A2b. Disbursement — B2B (our Paybill → a sub-merchant's Paybill)

We settle each ISP to **their own** paybill. Two things we need to know:

| Amount band (KES) | Fee charged to us (KES) |
|---|---|
| 1 – 1,000 | |
| 1,001 – 5,000 | |
| 5,001 – 20,000 | |
| 20,001 – 50,000 | |
| 50,001 – 150,000 | |
| 150,001 – 250,000 | |

**Critical for our onboarding flow:** when we send a B2B payment, is there a field
(`AccountReference`, `Remarks`, or similar) whose value the **recipient can see on
their own statement / confirmation SMS**? __________

> We verify that an ISP genuinely controls the paybill they registered by sending a
> small B2B payment carrying a random reference and asking them to read it back. If
> the recipient cannot see a reference we set, please tell us what they *can* see.

### A2c. C2B External Validation (not a tariff question — but critical)

Our customers pay by Paybill quoting an **account number** that routes the payment
to the correct sub-merchant (ISP) and subscriber. A mistyped account number means
money arrives attributed to nobody.

1. Can **External Validation** be enabled on our shortcode, so Safaricom calls our
   **Validation URL** *before* accepting a C2B payment and we may **reject** an
   unrecognised account number? ☐ Yes ☐ No — __________
2. If yes: what is the process/lead time to switch it on? __________
3. What exactly does the payer see when we reject? __________
4. Is there any charge for validation callbacks? __________

> Without this, every customer typo becomes real money stranded on our paybill and
> a subscriber cut off despite having paid. With it, the payer is simply told the
> account number is wrong and keeps their money.

### A3. Tax, failures, and volume

1. Are the fees above **inclusive or exclusive of Excise Duty** on transaction charges? If
   exclusive, what rate applies and to whom is it billed? __________
2. What is the cost of a **reversed / failed** transaction, if any? __________
3. Do **volume-based / negotiated tariffs** apply above a monthly value or count threshold?
   If so, please state the thresholds and the reduced rates. __________
4. Any **monthly standing charges, minimums, or API access fees** on the shortcode? _______
5. Applicable **rate limits / TPS** on C2B confirmation and B2C on Daraja at scale? _______

---

## PART B — I&M Bank (ISP disbursement via bank)

Used when an ISP chooses a **bank withdrawal** instead of M-Pesa. Intended to run over the
I&M host-to-host (H2H) API later; manual for now.

### B1. Per-transfer cost

| Rail | Cost per transfer (KES) | Amount cap / notes |
|---|---|---|
| **Pesalink** (to any bank) | | typically ≤ 999,999 |
| **EFT** (batch, next-day) | | |
| **RTGS** (large value) | | |
| **Internal** (I&M → I&M) | | |

### B2. Bulk & API

1. Is there **bulk/file-based disbursement** pricing that differs from single transfers? ____
2. **H2H API**: one-time setup fee? monthly fee? per-call fee? __________
3. **Settlement timing** per rail (Pesalink real-time, EFT T+1, etc.)? __________
4. Any **monthly minimums or maintenance fees** on the collection/settlement account? ______
5. **Volume-negotiated** rates — thresholds and reduced pricing? __________

---

## Response

- Schedule effective date: __________
- Prepared by (name / role): __________
- Contact for follow-up: __________

Please return the completed tables. If any rate is negotiable at our projected volumes
(multiple ISPs, target six-figure monthly collection value), we would like to discuss a
commercial arrangement.

---

## Appendix — INTERNAL ONLY (do not send)

How each confirmed answer maps to the platform config in
`backend/apps/billing/tariffs.py` (all `settings`-overridable, no code change):

| RFI item | Setting key | Notes |
|---|---|---|
| A1 free threshold | `MPESA_COLLECT_FREE_UNDER` | If customer bears C2B fee → set collection cost to **0** everywhere |
| A1 band % / flat | `MPESA_COLLECT_PCT` (+ per-band override) | If banded flat rather than %, replace `collection_cost()` with a band table like B2C |
| A1 cap | `MPESA_COLLECT_CAP` | |
| A2 payout bands | `MPESA_B2C_BANDS` = `[(upper, cost), …]` | Enter A2 table verbatim |
| A2 top band | `MPESA_B2C_COST_MAX` | Cost above the highest band |
| B1 Pesalink/EFT | `BANK_PAYOUT_COST` | Flat; extend to banded if I&M quote is banded |
| A3 excise | (fold into the above figures) | Store **excise-inclusive** costs so reconciliation matches the statement |
| A0 settlement timing | (ops note) | Drives how long float sits before payout; affects working capital |

**After the numbers are in:** set the keys, run `pytest` + platform reconciliation, and
verify — at the **bottom tier** (KES 30, where large ISPs blend to) — that
`per_user_fee − collection_cost(high-value package) > 0` with headroom. If thin, raise
the tier floor in `PPPOE_USER_FEE_TIERS`. See
[PRE_STAGING_CHECKLIST.md](PRE_STAGING_CHECKLIST.md) §1.

> §A1 is the pivotal question. **Customer-paid C2B** → collection costs us ~nothing and
> the current 40/35/30 ladder is very profitable (room to cut as a competitive move).
> **Merchant-paid C2B** → we absorb it, and the ladder must clear the collection cost on
> high-value packages.
