# Pre-Staging Checklist

Two gates must close before we move from development to staging:

1. **Confirm real transaction tariffs** and verify the pricing model still profits.
2. **Validate real hardware** — PTP/PTMP radios and every router model an ISP might bring.

---

## 1. Transaction-tariff confirmation

Danamo is a full-custody aggregator: it **absorbs** every M-Pesa/bank cost. Our
pricing (3% hotspot, graduated PPPoE 40/35/30) is provisional until the *real*
cost of moving money is known — because we absorb collection costs, **gross is not
net**, and this rate has outsized leverage on true margin.
`apps/billing/tariffs.py` currently uses **estimates**; they must be replaced with
confirmed figures.

### Numbers to obtain

| From | Figure | Why it matters |
|---|---|---|
| Safaricom (Paybill C2B) | Cost to **receive** a customer payment on the Danamo paybill, across amount bands | Sets the collection cost we absorb on every hotspot + PPPoE payment |
| Safaricom (B2C) | Cost to **pay out** to an ISP's M-Pesa, per amount band | Sets payout cost when ISPs withdraw to M-Pesa |
| I&M Bank (Pesalink/EFT) | Cost per bank transfer (flat or banded) | Sets payout cost for bank withdrawals |

> Paybill C2B tariffs often differ from the Till/Lipa-na-M-Pesa rate the
> estimates were based on — this is the single most important number to confirm,
> because PPPoE collection cost scales with package price.

### Where the confirmed numbers plug in

All are `settings`-overridable (no code change — set in `config/settings` or env):

| Setting | Meaning | Current estimate |
|---|---|---|
| `MPESA_COLLECT_PCT` | C2B collection % of amount | `0.55` |
| `MPESA_COLLECT_CAP` | Max collection cost per payment | `200` |
| `MPESA_COLLECT_FREE_UNDER` | Amount at/below which collection is free | `200` |
| `MPESA_B2C_BANDS` | `[(upper, cost), …]` payout bands | `[(1000,20),(5000,35),(20000,50)]` |
| `MPESA_B2C_COST_MAX` | Payout cost above the top band | `60` |
| `BANK_PAYOUT_COST` | Flat bank transfer cost | `0` |

### Verify margin after confirming

Once the real numbers are in, run the platform reconciliation (or the finance
tests) and confirm on a **high-value PPPoE package** (e.g. KES 5,000/mo) that, at
the **worst-case tier** (large ISPs blend down to KES 30/user):

```
per_user_fee (30 at the bottom tier)  −  collection_cost(package_price)  >  0
```

If a KES 5,000 payment costs more than ~KES 20 to collect, the bottom tier leaves
thin margin — raise the tier floor via `PPPOE_USER_FEE_TIERS`. The monthly true-up
(reconciliation's `transaction_costs` vs `net_margin`) keeps estimates honest in
production.

**The pivotal answer is *who bears the C2B charge* (RFI §A1):**
- **Customer-paid** → collection costs us ~0. Current rates are very profitable;
  we have room to *cut* them as a deliberate competitive move.
- **Merchant-paid** → we absorb it. Verify the bottom tier still clears on
  high-value packages; the 40/35/30 ladder was chosen with this case in mind.

- [ ] C2B charging model confirmed (customer- vs merchant-paid) ← **decides everything**
- [ ] C2B collection tariff confirmed and set
- [ ] B2C payout bands confirmed and set
- [ ] I&M bank transfer cost confirmed and set
- [ ] Margin verified positive on low- and high-value packages, at every tier
- [ ] PPPoE tiers finalised (lock 40/35/30 or adjust)

---

## 2. Real hardware validation

### Router connectivity + capability — every model

For each physical router (and each **model** an ISP might onboard), run the
read-only smoke test. It authenticates, reads board/version/health, and counts
live sessions — it changes nothing on the device:

```
docker compose exec api python manage.py router_smoketest --router <id>
```

Record a pass per model:

| Model | RouterOS | Arch | Smoke test | Notes |
|---|---|---|---|---|
| RB951Ui-2HnD | 7.16.2 | mipsbe | ✅ | Pilot router, proven |
| hAP ac² | | | ☐ | |
| RB4011 / RB5009 | | | ☐ | ARM — confirm REST parity |
| CCR (cloud core) | | | ☐ | High-capacity PPPoE |
| CHR (x86/VM) | | | ☐ | If used as a NAS/aggregator |

> RouterOS **v7 REST** is required. If an ISP runs v6, the adapter won't talk to
> it — flag during onboarding.

### End-to-end PPPoE lifecycle on real hardware

Beyond connectivity, confirm the full provisioning path on at least one real
router per architecture (mipsbe already proven on the RB951). Via the ISP
console (Broadband → Clients):

- [ ] Create client → **Provision** → client appears in `/ppp/secret`, can dial in
- [ ] **Suspend** → session dropped, redirected to the `/suspended` page
- [ ] Pay via C2B → auto-restore → back online
- [ ] **Remove** → `/ppp/secret` entry gone
- [ ] Factory-reset the router → **Reprovision** from the UI re-syncs it

### PTP / PTMP radio delivery

For wireless clients behind CPE radios (CPE510 PTP, sector PTMP):

- [ ] PTP link client provisions and passes traffic through the radio link
- [ ] PTMP sector: multiple clients on one AccessPoint, capacity/utilisation
      reflected in Network view (seed reference: `python manage.py seed_network`)
- [ ] Suspend/restore works through the radio path (redirect reaches the client)
- [ ] Confirm the AccessPoint capacity numbers match what the sector really holds

---

## Exit criteria

- [ ] Section 1 complete — tariffs confirmed, margin verified, PPPoE rate locked
- [ ] Section 2 complete — every target router model smoke-tested green, PPPoE
      lifecycle proven on real hardware, PTP + PTMP validated
- [ ] Full test suite green (`DJANGO_SETTINGS_MODULE=config.settings.test pytest`)

Then: staging deploy.
