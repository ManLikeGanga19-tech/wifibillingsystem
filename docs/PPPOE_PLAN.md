# Phase 3 — PPPoE / Broadband Architecture

Design agreed with Daniel 2026-07-11. No code until this is the reference.
Decisions: (1) PPPoE now, static-IP+Queue later; (2) suspend = redirect-to-pay page;
(3) FULL towers/sectors/APs topology model; (4) anniversary billing.

## Core insight

PPPoE is **media-agnostic**: fibre, ethernet, and CPE510 wireless PTP/PTMP clients
all authenticate identically (a PPPoE username/password → speed profile). Last-mile
only changes how packets reach the router, not billing/provisioning. So:
- **Service layer** (auth + rate-limit + billing) = uniform PPPoE.
- **Delivery/topology layer** (fibre/ethernet/PTP/PTMP, towers, sectors, CPE) =
  metadata + equipment + capacity, orthogonal to billing.

## New app: `pppoe` — isolated from hotspot

Shares only: tenant `operator` scoping, Router records, wallet/ledger, adapter
pattern. Everything else is separate (own plans, clients, invoices, MikroTik
objects). Hotspot uses `/ip/hotspot/user`; PPPoE uses `/ppp/secret` + `/ppp/profile`.

### Models

**pppoe.ServicePlan** (the broadband package — separate from hotspot plans)
- operator, name, monthly price (KES), download_kbps, upload_kbps
- burst_limit / burst_threshold / burst_time (optional MikroTik burst)
- data_cap_gb (nullable = unlimited FUP), mikrotik_profile (the /ppp/profile name)
- is_active

**pppoe.Client** (the contracted account an ISP sets up)
- operator, **account_number** (GLOBALLY unique — see aggregator note), full_name,
  phone, email, physical_address, gps_lat/gps_lng (optional)
- plan FK (ServicePlan), router FK (which router serves them)
- pppoe_username, pppoe_password, static_ip (nullable)
- delivery_method: fibre | ethernet | wireless_ptp | wireless_ptmp
- access_point FK (nullable — which sector/AP they connect to; wireless)
- cpe_equipment FK (nullable — their CPE radio/ONT in Equipment inventory)
- status: pending_install | active | suspended | disabled
- billing_day (1–28), installed_at, balance (running credit), next_due_date
- notes, created_by

**pppoe.Invoice**
- operator, client, period_start, period_end, amount, due_date
- status: unpaid | paid | overdue | cancelled ; issued_at, paid_at

**Network topology (FULL model — chosen)**
- **pppoe.Tower** (Site): operator, name, gps_lat/lng, notes, is_active
- **pppoe.AccessPoint** (Sector/AP): operator, tower FK, name, mode (ap/ptp/ptmp),
  band/frequency, azimuth (optional), capacity (max clients), router FK +
  interface (optional), equipment FK (the radio), ssid, is_active
- Client.access_point FK → utilization = active clients / capacity per AP.
  Dashboard: tower/sector load, oversubscription warnings.

### Aggregator constraint (critical)

All ISPs share Danamo Tech's paybill, so the **account_number is globally unique** —
it's the only key the C2B confirmation has to route a payment to the right ISP AND
client. Format e.g. `<TENANTPREFIX>-<seq>` (HL-04231). Uniqueness enforced globally.

## Provisioning (extend `provisioning` adapter)

System manages the SAFE, uniform objects only:
- create/enable/disable/remove_pppoe_user → /ppp/secret (name, password, profile,
  service=pppoe, remote-address=static_ip?)
- ensure_profile(plan) → /ppp/profile (rate-limit up/down + burst)
- get_active_pppoe(router) → /ppp/active (live who's-online)

System does NOT auto-configure the PPPoE server, IP pools, VLANs or per-sector
interfaces (varies per ISP; auto-touching breaks live networks). Assume/one-time-
script a working PPPoE server; thereafter we only push secrets + profiles.

### Suspend = redirect-to-pay (chosen)

Suspended clients keep a link but every web request hits a payment-due page showing
their account number + how to pay. Implementation: a "blocked" /ppp/profile that
puts the client on an address-list; a firewall + walled-garden redirect (or a small
web-proxy redirect) sends http to a notice page. Restore = move back to normal
profile. Needs a one-time redirect setup on the router (documented, part of onboarding).

## Billing lifecycle (anniversary — chosen)

- Each client billed on their own billing_day each month (install day). Smooths load.
- Daily beat: issue invoices due on billing_day; mark overdue past grace; auto-suspend
  overdue-past-grace (redirect profile); grace_days configurable per operator.
- C2B confirmation (Danamo paybill): BillRefNumber = account_number → find Client
  (global) → credit balance → settle oldest unpaid invoice(s) → auto-restore if
  suspended. Idempotent on M-Pesa TransID; store raw payload.
- Wallet: PPPoE payment credits the ISP wallet in full; monthly the platform deducts
  (active PPPoE clients × pppoe_user_fee) via a ledger line (per the business model).
  Platform-owned ISP exempt (is_platform_owned).

## Payments (extend `payments`)

- New **C2BPayment**: trans_id (unique, idempotent), bill_ref (account_number),
  msisdn, amount, raw_payload, matched Client/Invoice, status.
- Register C2B validation+confirmation URLs once on Danamo's shortcode. Validation
  may reject unknown account numbers; confirmation applies payment.
- STK Push (hotspot) untouched.

## ISP-facing UI (v1)

- **Broadband** sidebar group: Clients, Service Plans, Invoices, Network (towers/APs).
- **Client setup wizard**: details → plan → router → delivery method → (AP if wireless)
  → auto-generate account number + PPPoE creds → push secret → mark installed.
- **Client detail**: account number, plan, LIVE status (/ppp/active), invoices,
  payments, suspend/restore, edit.
- **Printable account sheet**: account number, how to pay via M-Pesa, plan, support.
- **Network view**: towers → sectors with utilization (active/capacity), oversub flags.
- Customer self-service portal (client checks balance / pays) = DEFERRED to a later
  phase; v1 is ISP-managed.

## RBAC / tenancy

All models operator-scoped via TenantScopedMixin. Roles: owner/manager manage clients
+ plans + network; support read-only. Money actions (write-offs, manual credits) =
owner. Platform staff view-as as usual.

## Build order (when we start)

1. Models + migrations (pppoe app: ServicePlan, Client, Invoice, Tower, AccessPoint) +
   C2BPayment in payments. Account-number generator (globally unique).
2. Provisioning: PPPoE adapter methods + profile sync + suspend/restore (redirect).
3. Billing engine: anniversary invoicing beat, overdue→suspend, grace.
4. C2B: register URLs, confirmation matching, wallet credit, auto-restore, idempotency.
5. Platform per-user fee metering (monthly).
6. UI: Broadband section (clients wizard/detail, plans, invoices, network, account sheet).
7. Tests: account-number uniqueness/routing, C2B idempotency + matching, invoice
   anniversary, overdue→suspend→pay→restore, AP capacity, tenant isolation.
8. Verify on real RB951 (create PPPoE server, provision a test secret, dial in).

Deferred: static-IP + Simple Queue mode (adapter designed to accept it), customer
self-service portal, multi-service-per-customer.
