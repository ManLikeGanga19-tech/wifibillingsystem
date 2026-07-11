# Payments Architecture — Central Custody (Aggregator)

Agreed with Daniel 2026-07-11. All ISP money flows through Danamo Tech first,
is attributed per-ISP in the ledger, then disbursed. Provider-abstracted so rails
swap without touching billing.

## Money map

```
MONEY IN (collection — all to Danamo)
  Hotspot customer → STK Push ─┐
  PPPoE customer   → C2B (paybill + account no.) ─┤→ Danamo M-Pesa (Daraja)
                                                   └→ settles to Danamo I&M bank a/c
CUSTODY + LEDGER (WIFI.OS)
  each payment attributed to its ISP (plan.operator / account_number)
  ISP wallet credited = amount − platform cut
  platform earns: 3% hotspot + per-PPPoE-user fee + base fee
MONEY OUT (disbursement — Danamo → ISP)
  ISP Withdraw → platform payout queue → execute
    v1: MANUAL (mark paid)  [built]
    later: I&M H2H API (banks/Pesalink/RTGS/M-Pesa)  [designed toward]
RECONCILE (platform float view)
  Danamo balance == Σ ISP wallets + platform earnings − disbursed − fees
```

Money never touches an ISP directly. Aggregation touches CBK/PSP rules — I&M
partnership helps formalise; raise with I&M.

## Provider abstraction (mirrors the provisioning adapter pattern)

**CollectionProvider** (money in)
- `DarajaProvider`: STK Push (hotspot) + C2B (PPPoE). BUILT/extending.
- Cost: Daraja till 0.55% capped KES 200, ≤200 free — platform cut must exceed this.

**DisbursementProvider** (money out)
- `ManualProvider`: v1 — platform pays, records M-Pesa/bank ref. BUILT.
- `IMBankProvider`: I&M Host-to-Host API — pay ISPs to bank/Pesalink/RTGS/M-Pesa.
  CHOSEN target for automation; plugs in when I&M credentials + partnership ready.
  H2H = STP over secure VPN/point-to-point; 2FA (token + creds); return file for
  auto-reconciliation.
- `DarajaB2CProvider`: possible later for M-Pesa payouts (has M-Pesa limits).

Decision: keep payouts MANUAL for now; ship PPPoE first; automate disbursement
(I&M) as its own later phase. Design the DisbursementProvider interface now so it
drops in without billing changes.

## Reconciliation / float (basic, build with Phase 3)

Platform-only screen (IsPlatformStaff):
- Total collected (period + all-time)
- Total owed to ISPs = Σ wallet balances
- Platform earnings = Σ commissions + fees
- Total disbursed (paid payouts)
- Current float / expected Danamo balance
- Per-ISP breakdown; flag mismatches
Gives audit/trust while holding everyone's funds.

## Not building now (deferred)

I&M H2H integration (until partnership + credentials), Daraja B2C, card/bank
collection, customer self-service payment portal.
