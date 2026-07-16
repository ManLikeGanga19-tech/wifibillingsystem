# WireGuard management plane

**Status:** design agreed 2026-07-16. Not built. This is the connectivity substrate the
whole SaaS rides on, and the hard prerequisite for onboarding the **second** ISP.

## Why

The control plane (Django on a VPS) has to reach every ISP's MikroTik router to do its job:
push hotspot users, provision PPPoE secrets, poll usage, sync sessions, push the captive
portal. Today it works because the pilot router answers on a LAN IP (`192.168.2.240`) and
M-Pesa callbacks return over an ngrok tunnel. **Neither survives contact with a real ISP.**

Kenyan ISPs are overwhelmingly behind **CGNAT**. Their router has no stable public IP, and
they can't port-forward carrier NAT they don't control. So the control plane cannot *dial
in* to the router at all. Asking each ISP to buy a static IP or run their own VPN is a
non-starter for onboarding.

The fix is the standard one for fleet device management (OpenWISP, Tailscale, Netbird, every
commercial WISP controller): the router **dials out** to a concentrator we run, and the
control plane addresses it back down that tunnel. WireGuard is the transport.

Getting this right also **de-risks every future data-plane change** (VLANs, firewall, portal
pushes): if management rides its own out-of-band tunnel, a misconfiguration on the customer
data plane can never sever our control of the router. See `docs/VLAN_SEGMENTATION.md`.

## Decisions (agreed)

- **WireGuard, native in RouterOS 7** (`/interface/wireguard`). Kernel-level, tiny, survives
  IP changes, punches NAT with `persistent-keepalive`. Not OpenVPN (heavy), not IPsec (a
  config minefield), not an SSH reverse tunnel (fragile).
- **Hub-and-spoke, not mesh.** We only need control-plane ↔ router. We will **not** adopt a
  mesh product (Tailscale / Headscale / Netbird) — that is magic rented for a topology we
  don't have. A plain WG hub we fully own is simpler, dependency-free, and auditable.
- **Phone-home.** The router always initiates the tunnel (outbound), so CGNAT is irrelevant.
- **Per-`/32` peer isolation is a security invariant**, not a nicety: routers must never be
  able to reach each other over the overlay.
- **Manage over the overlay, never over a customer/data VLAN.** The overlay is the only
  management path, which is what makes remote data-plane changes survivable.
- **Keys encrypted at rest** (Fernet, per the no-secrets-in-code rule); the enrollment token
  is the single-use bootstrap secret.

## Architecture

### Topology

```
        ISP A premises (CGNAT)          ISP B premises (CGNAT)
        ┌───────────────────┐           ┌───────────────────┐
        │  RouterOS  wg0     │           │  RouterOS  wg0     │
        │  10.88.0.5/32      │           │  10.88.0.6/32      │
        └─────────┬─────────┘           └─────────┬─────────┘
                  │ outbound WG (UDP 51820), keepalive 25s
                  │                                │
                  ▼                                ▼
            ┌───────────────────────────────────────────┐
            │   WireGuard hub  (10.88.0.1)                │
            │   - one peer per router, allowed-ips = /32  │
            │   - NO peer-to-peer forwarding              │
            │   - firewall: routers may reach ONLY the    │
            │     control plane; nothing router↔router    │
            └───────────────────┬───────────────────────┘
                                │ overlay only
                                ▼
            ┌───────────────────────────────────────────┐
            │  Control plane (Django/Celery)             │
            │  adapter REST → https://10.88.0.5/rest/... │
            └───────────────────────────────────────────┘
```

The control plane never talks to a router's public IP again. It talks to `10.88.0.<n>`.

### Key & IP management

Each `Router` row gains:

- a WireGuard **keypair** — private key encrypted at rest, public key stored plainly (it is
  public by definition and must be registered on the hub);
- an allocated **overlay IP** — a `/32` from a pool (`10.88.0.0/16` ⇒ ~65k routers; grow to
  `10.64.0.0/10` if we ever need millions). Allocation is a monotonic counter or a released
  pool; store `overlay_ip` on the router.

The **hub** holds one WireGuard peer per router: `public-key`, `allowed-address = <overlay
IP>/32`, and the router's last-known endpoint (learned from the inbound handshake — we never
need to know it in advance, which is the point).

### Enrollment flow

Enrollment reuses the existing one-time `enrollment_token` on `Router`. The flow:

1. **ISP adds a router** in the console → we generate the keypair, allocate the overlay IP,
   register the peer on the hub, and mint a short-lived single-use enrollment token.
2. **Console shows a one-paste setup script** (the MIKROTIK_SETUP.md pattern, extended). It
   contains: create `/interface/wireguard wg0` with the router's private key; add a peer =
   the hub (its public key, public endpoint, `allowed-address=10.88.0.0/16`,
   `persistent-keepalive=25s`); assign `10.88.0.<n>/32` to `wg0`; create the API user we
   provision through. The private key is in the script, fetched **once** over TLS, never
   stored in the browser (no-browser-storage rule).
3. **Router dials the hub**, handshake completes, `wg0` comes up.
4. **Control plane flips the router's `management_host` to the overlay IP** and runs the
   existing `test_connection` health check. Green ⇒ enrolled; the enrollment token is burned.

Re-enrollment (factory reset, lost key) issues a fresh token + keypair and revokes the old
peer on the hub.

### Control-plane addressing — the payoff of the adapter seam

The `ProvisioningAdapter` already builds `rest_base_url` from `Router.management_host`. Post-
enrollment that is the overlay IP, so **nothing in the provisioning layer changes** — the
hotspot/PPPoE/portal code is untouched. This is the whole reason the adapter abstraction was
worth having.

### Liveness

The hub's **last-handshake per peer** is an independent health signal. A router whose tunnel
is dead is unreachable no matter what a stale API check says. We read peer status from the
hub (a thin admin endpoint or the WG kernel interface) and fold it into router health
alongside the REST check — two independent signals, not one.

## Data model (sketch)

`Router` gains: `wg_private_key` (encrypted), `wg_public_key`, `overlay_ip`,
`wg_enrolled_at`, `wg_last_handshake_at`. An `OverlayAllocation` (or a simple counter table)
owns IP assignment so two routers can never get the same `/32`. Hub peer state is derived,
not a source of truth — the DB is authoritative; the hub is reconciled from it.

## Security invariants (must hold, tested)

1. **Peer isolation.** Every peer's `allowed-address` is exactly its `/32`, and the hub does
   **not forward between peers.** ISP A reaching ISP B's router over the overlay would be a
   cross-tenant L3 breach. Enforced by per-`/32` allowed-ips **and** a hub firewall.
2. **Routers reach the control plane and nothing else.** Hub firewall permits
   router → control-plane API only; drops router → router and router → internet-via-hub.
3. **Two independent layers.** WG is transport; the RouterOS API user/password is authz. A
   compromised tunnel still faces the API credential (encrypted, per-router).
4. **Enrollment token is single-use and short-lived**, and authorizes exactly one router to
   claim exactly one overlay `/32`.
5. **Keys never touch the browser store or source.** Private keys are Fernet-encrypted at
   rest and streamed to the setup script once over TLS.

## Failure modes & operations

- **Hub is a single point of failure.** At pilot scale, one hub + monitoring is acceptable;
  before it is load-bearing for many ISPs it needs a **warm standby** (a second hub, peers
  configured on both, routers list both as endpoints) and eventually **regional
  concentrators** to keep control-plane latency sane.
- **NAT rebinding / roaming.** `persistent-keepalive=25s` keeps the mapping open and lets the
  router move networks (LTE failover, new WAN) without manual intervention.
- **Overlay exhaustion.** `/16` is ample; monitor allocation and alert at 80%.
- **Key rotation.** Rotating a router's key = generate new pair, update the hub peer, push the
  new key via a re-enrollment script. Design for it now (store `wg_enrolled_at`), automate
  later.
- **Clock/observability.** Track `wg_last_handshake_at` per router; a fleet view of "tunnels
  down" is a first-class operational screen (like the "paid but not connected" queue).
- **Bootstrapping trust.** The window between "peer registered on hub" and "router dials in"
  is where a leaked token matters — hence single-use + short TTL + audit line on enrollment.

## What this is NOT (scope guardrails)

- **Not a mesh / SD-WAN.** Hub-and-spoke only. No router-to-router, no site-to-site for the
  ISP's own network — that is their concern, not the platform's.
- **Not a general VPN for the ISP.** The overlay carries **management only**, never customer
  traffic.
- **Not Tailscale-with-extra-steps.** If we ever needed mesh we would adopt one; we don't, so
  we own a ~200-line hub instead of renting a control plane.

## Phased build

1. **MVP (before ISP #2):** one hub on the VPS; per-router keypair + overlay IP; enrollment
   script generates the WG stanza; adapter uses the overlay IP; peer isolation + hub firewall;
   handshake-based liveness. This is the genuinely-needed slice.
2. **Resilience:** warm-standby hub; automated key rotation; overlay-exhaustion alerting.
3. **Scale:** regional concentrators; per-region hub selection at enrollment; anycast or DNS-
   based hub failover.

## Open questions to confirm before build

- **Where does the hub live** — on the app VPS (simplest, shared blast radius) or a dedicated
  small box (cleaner isolation, one more thing to run)? Lean dedicated once past pilot.
- **Overlay CIDR** — `10.88.0.0/16` proposed; confirm it can't collide with any ISP's LAN or
  our own infra addressing.
- **Hub implementation** — `wg-quick` + nftables + a tiny reconciler that syncs peers from the
  DB, vs `wg` netlink from Python. Reconciler-from-DB is the auditable choice (DB is truth).
- **Callback path** — does the M-Pesa callback also move onto stable infra (real
  `api.wifios.co.ke`) at the same time, retiring ngrok? Almost certainly yes; they ship
  together.

## Testing strategy

- **Unit:** keypair generation, overlay-IP allocation never double-assigns, enrollment token
  single-use, peer config renders correct allowed-ips (`/32`).
- **Isolation test (the important one):** assert the generated hub config never grants a peer
  more than its `/32`, and that a second router cannot be addressed from a first over the
  overlay (config-level assertion + an integration test against two dummy peers).
- **Enrollment integration:** dummy router "dials in", control plane flips to overlay IP, the
  existing `test_connection` passes; token is burned; re-enrollment revokes the old peer.
- **Liveness:** a peer with a stale handshake is reported unreachable even when a cached REST
  check is green.

## Related

- `docs/ONBOARDING_ARCHITECTURE.md` — router enrollment this extends.
- `docs/MIKROTIK_SETUP.md` — the setup script the WG stanza joins.
- `docs/VLAN_SEGMENTATION.md` — the data plane this management plane makes safe to change.
- `docs/THREAT_MODEL.md` — peer isolation belongs in the tenant-isolation invariants.
