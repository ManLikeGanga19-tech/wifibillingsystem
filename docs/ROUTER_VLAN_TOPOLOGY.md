# Router VLAN topology — the canonical target

**Status:** validated on the pilot RB951 (RouterOS 7.16.2) on 2026-08-03. This is the clean
topology every tenant ISP's router should end up in. `provisioning.onboarding.generate_setup_script`
does **not** emit this yet (see "Generator rewrite" below) — it was applied here by hand /
over REST and this doc is the spec that rewrite targets.

## Why VLANs (not flat)

A flat L2 lets a hotspot customer ARP-scan the router's management interface — a real
cross-plane vulnerability (this is exactly how the operator got trapped by the captive
portal while trying to manage the box). VLANs put each plane on its own segment:

- **Hotspot** (walk-in, prepaid) and **PPPoE** (fixed-line, monthly) coexist on one board.
- Neither customer plane can reach **management**, or **each other**.
- A managed-switch **trunk** carries the customer VLANs to the access network — so an ISP
  who already runs VLANs plugs in and we honour their tags. VLAN IDs are per-device, never
  global (two ISPs both using VLAN 30 on their own hardware is not a conflict).

## The layout (RB951, 5 ports + wlan)

| Port | Role | PVID / tagging |
|---|---|---|
| ether1 | WAN uplink **+ management** (off the VLAN bridge) | untagged, own subnet |
| ether2 | PPPoE access (direct CPE / test) | pvid 30 |
| ether3 | **tagged trunk** to a managed switch | tagged 20 + 30 |
| ether4, ether5, wlan1 | Hotspot access | pvid 20 |

| VLAN | Role | L3 interface | Subnet |
|---|---|---|---|
| 20 | Hotspot | `vlan-hotspot` | `10.5.50.1/24` (pool `.10–.254`) |
| 30 | PPPoE | `vlan-pppoe` | `10.6.0.1/24` (pool `10.6.0.10–.254`) |
| 10 | *(reserved: mgmt)* | — | later / WireGuard overlay |
| 40 | *(reserved: IPTV)* | — | TV add-on |

`bridgeLocal` runs with `vlan-filtering=yes`; the bridge is a **tagged** member of 20 & 30
so its own L3 VLAN interfaces work. Management stays on **ether1**, off the bridge, so
flipping vlan-filtering can never sever the control plane (and it didn't).

## Services bound

- Hotspot server → `vlan-hotspot`; DHCP `hs-dhcp` → `vlan-hotspot`.
- PPPoE server → `vlan-pppoe`; default profile `pppoe-default` (`local 10.6.0.1`,
  `remote pppoe-pool`); suspended profile `wifios-suspended` (128k throttle) for
  redirect-suspend.

## Security invariants (validated)

- `www`, `ssh`, `winbox` IP-services restricted to the **management subnet** only — a
  customer on a VLAN cannot reach them. (`telnet/ftp/api/www-ssl` stay disabled.)
- Forward-chain isolation drops:
  - `fw-8` hotspot `10.5.50.0/24` → mgmt
  - `fw-9` pppoe `10.6.0.0/24` → mgmt
  - `fw-10` hotspot → pppoe, `fw-11` pppoe → hotspot (inter-customer isolation)
- Least-privilege API user (`wifios-api` group: `read,write,api,rest-api,!ftp,!telnet,
  !ssh,!reboot,!sensitive`) — cannot take backups or touch sensitive data. Confirmed: a
  backup attempt as this user is correctly refused.

## Bug found & fixed on real hardware

`MikroTikRestAdapter.ensure_pppoe_profile` created plan profiles with the rate-limit but
**no `local-address`/`remote-address`** — a subscriber authenticated against such a profile
would come up with **no IP** (a dead line). Fixed: the adapter now copies the pool +
gateway from the PPPoE server's default profile onto every plan profile, so it works on any
router without extra config and never invents a pool. Covered by
`tests/test_pppoe_profile_addressing.py`; validated live (a provisioned test subscriber's
profile now carries `10.6.0.1` / `pppoe-pool`).

## Generator rewrite (next)

`generate_setup_script` must be rebuilt to emit exactly the above, and must be:

1. **Idempotent** — the current version uses `add` everywhere and piles up duplicates on
   re-run (two hotspots, three pools, a dangling bridge were the result). Use
   `:if ([... find ...]="") do={ add } else={ set }` guards, or remove-then-add.
2. **VLAN-aware** — the bridge-vlan table, PVIDs, trunk, and both VLAN L3 interfaces.
3. **PPPoE-complete** — server on `vlan-pppoe`, pool, `pppoe-default` + `wifios-suspended`.
4. **Isolation + service lockdown** built in. The lockdown *subnet* is environment-specific
   (a LAN subnet pre-WireGuard, the `10.88.0.0/16` overlay after) — so parameterise it, and
   pair this rewrite with the **WireGuard management plane** (`docs/WIREGUARD_MANAGEMENT_PLANE.md`),
   which is where management addressing becomes stable and remote-safe.

## Related

- `docs/MIKROTIK_SETUP.md` — the human setup guide.
- `docs/VLAN_SEGMENTATION.md` — the segmentation design (awareness vs lifecycle).
- `docs/WIREGUARD_MANAGEMENT_PLANE.md` — the prerequisite for remote/automated pushes.
