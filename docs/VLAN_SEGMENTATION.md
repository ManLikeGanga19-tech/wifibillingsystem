# VLAN segmentation

**Status:** PARKED — post-production. Design thinking captured 2026-07-16 so it isn't lost.
Not to be built now. Read the scope guardrail before anyone picks this up.

## Why this is parked, not scheduled

WIFI.OS is a **billing + provisioning + collection** product. VLANs are **L2 infrastructure
automation** — a different centre of gravity. Building full VLAN lifecycle management drifts
the product toward being an OpenWISP / UniFi network controller, which is a much larger and
different product than "get an ISP paid."

For the current stage (hotspot + basic PPPoE, single-tower pilots) VLANs are **premature**.
They earn their place only when an ISP has (a) a real multi-sector tower topology, (b) service
tiers that need traffic/QoS separation, or (c) IPTV. When that demand is real and paying, this
doc is the starting point.

**Prerequisite:** do **not** start VLAN automation before the WireGuard management plane
(`docs/WIREGUARD_MANAGEMENT_PLANE.md`) exists. A bad VLAN push can black-hole a sector or move
management onto a VLAN you can no longer reach — bricking a router hundreds of km away.
Out-of-band management over the WG overlay is what makes data-plane VLAN changes survivable.

## What VLANs buy a WISP (priority order for this business)

1. **Service separation** — hotspot / PPPoE / **management** / IPTV each on its own VLAN with
   its own pool, firewall and QoS. The security-critical case is keeping **customers off the
   management VLAN**: a flat L2 where a hotspot user can ARP-scan the router's management
   interface is a real vulnerability.
2. **Per-sector / per-tower segmentation** — each sector AP on an access VLAN. This is simply
   the L2 realisation of the Tower → Sector → AccessPoint topology the `pppoe` app **already
   models**, so the data model is half-built.
3. **Backhaul transport** — carrying many VLANs over a PtP/PtMP link as a trunk, sometimes
   Q-in-Q (S-VLAN per tower, C-VLAN per service/customer). How WISPs scale L2 over microwave
   or fibre.
4. **IPTV / multicast** — IPTV is almost always a dedicated VLAN with IGMP snooping. This ties
   directly to the **hotspot TV add-on** (`tv_slots`, tap-to-approve): a "TV service" is
   naturally "the IPTV VLAN + multicast", which is the cleanest future home for it.

## Shape when we build it

### Data model

A `NetworkSegment` (a.k.a. `Vlan`), operator-scoped:

- `vlan_id` (1–4094), `name`, `role` (hotspot | pppoe | mgmt | iptv | backhaul), `router` FK,
  `parent_interface` (bridge/trunk), `subnet`, `gateway`, `dhcp_pool`, `is_active`.
- **Uniqueness is `(router, vlan_id)`, never global.** VLAN IDs are a per-device L2 concept —
  two ISPs (or two of one ISP's routers) both using VLAN 100 on their own hardware is not a
  conflict. Global VLAN uniqueness would be a modelling error.

Associations, all optional:

- `Sector` / `AccessPoint → segment` — the access VLAN a sector lives on.
- `Plan → segment` — deliver a tier on its own VLAN (PPPoE-over-VLAN, or hotspot-on-VLAN).
- TV add-on → the IPTV segment.

### Provisioning (RouterOS specifics)

New adapter methods behind the existing `ProvisioningAdapter` seam:

- `/interface/vlan` (or, preferred, **`/interface/bridge/vlan`** — hardware-offloaded VLAN
  filtering on the switch chip).
- `/ip/pool` + `/ip/dhcp-server` per VLAN for DHCP/hotspot segments.
- Bind the hotspot server, or `/interface/pppoe-server`, to the VLAN interface.
- Firewall rules per VLAN (isolate mgmt, permit IPTV multicast) and queues/QoS per tier.

### The non-negotiable safety mechanism

**Commit-confirm / scheduled rollback.** Before applying a VLAN change: schedule a "restore
last-good backup in N minutes" job on the router, apply the change, then cancel the rollback
**only if the router is still reachable over the WG overlay**. Same class of safety as
changing a management IP. Without this, VLAN automation is a foot-gun.

Guard destructive edits (deleting/moving a VLAN that has active customers) the same
conservative way the hotspot/PPPoE prune logic guards deletion.

## Scope guardrail (read this before building)

Add **exactly enough VLAN awareness to bill and provision correctly onto the ISP's existing
L2 design** — and stop there. Resist becoming the ISP's network controller.

Concretely, if/when this is picked up, phase it:

1. **VLAN awareness (light):** let an ISP **record** their VLAN/interface map so plans and
   sectors target the right interface, and provision **onto existing VLANs**. Low risk,
   immediately useful — especially for the IPTV/TV path. This is the only slice likely ever
   worth doing.
2. **VLAN lifecycle (heavy, only on real demand):** full CRUD + DHCP + firewall + QoS
   automation with commit-confirm. Big surface, real brick risk, and the point where the
   product starts turning into something it isn't. Require a paying reason.

## Related

- `docs/WIREGUARD_MANAGEMENT_PLANE.md` — the prerequisite; makes VLAN changes survivable.
- `docs/PPPOE_PLAN.md` / the `pppoe` app — the Tower → Sector → AP topology VLANs would map to.
- Hotspot TV add-on (`Plan.tv_slots`, `SessionDevice`) — the IPTV-VLAN's natural future home.
