# PPPoE usage metering

**Status:** in progress. Design agreed 2026-07-14.

## Why

Fixed-line (PPPoE) subscribers are always-on and billed monthly. To run that business an
ISP needs to see who is online, what they are consuming against their fair-use cap, and to
be warned before a customer is surprised. The Settings > PPPoE page already exposes FUP
thresholds and pre-expiry reminders; this subsystem is the metering that makes FUP alerts
real and powers a live view of every line.

Distinct from the hotspot data-cap sync: hotspot is one time-boxed session with a
router-enforced cap. PPPoE is always-on, reconnects constantly, and accumulates over a
BILLING CYCLE across many sessions — which is the whole design challenge.

## Decisions (agreed)

- **Source: poll the routers now, RADIUS-ready.** Delta-poll the MikroTik interface
  counters. No new infrastructure; mirrors the working hotspot sync. The usage model is
  abstracted from the source so exact RADIUS accounting can plug in later without touching
  anything downstream.
- **Cadence: every 5 minutes.** Status/usage lag ≤ 5 min; 2 bulk calls per router.
- **FUP at 100%: alert only.** SMS at the chosen thresholds; no automatic speed change.

## How it works

### Source of truth on the router
`/ppp/active` does NOT expose live byte counters. Each connected client gets a dynamic
interface `<pppoe-{username}>`, and `/interface` exposes its `rx-byte`/`tx-byte` since the
session came up. So each poll makes **two BULK calls per router** and joins by username:

- `/ppp/active` → presence, `address` (WAN IP), `uptime`, `caller-id`
- `/interface` (pppoe dynamics) → `rx-byte`, `tx-byte`, running state

Two calls per router per poll, regardless of client count — flat scaling.

### Delta accumulation (survives reconnects)
The interface counter resets to zero on every reconnect, so we accumulate rather than read
a total:

```
delta = current − snapshot          # normal
delta = current                     # if current < snapshot → the session reconnected
usage += delta ; snapshot = current
```

This is resilient to reconnects, missed polls, and router reboots.

**Accuracy caveat (honest):** polling is approximate — bytes from a session that connects
AND disconnects entirely between two polls are lost. Standard trade-off, fine for FUP and
reporting. The exact alternative is RADIUS `Acct-Stop`; the model is built to accept it
later.

### Resilience
Best-effort per router: an unreachable box is skipped and accumulates nothing (never zeroed
out), exactly like `sync_hotspot_usage`.

## Data model

- **`Client`** gains live cache fields (cheap reads for the dashboard/list):
  `is_online`, `last_online_at`, `wan_ip`, `session_uptime`, `usage_synced_at`.
- **`ClientUsage`** (`client`, `period_start`): the accounting row per billing cycle.
  - `bytes_in`, `bytes_out` — cumulative for the cycle
  - `snapshot_rx`, `snapshot_tx`, `snapshot_at` — for delta continuity across polls
  - `fup_alerted` — JSON list of % thresholds already alerted this cycle (once each)
  - keyed per `(client, period_start)`, so history is retained and each cycle resets by
    starting a fresh row.

`period_start` is derived from the client's `billing_day` (the anniversary), so the cycle
lines up with invoicing.

## Tasks

- **`poll_pppoe_usage`** (beat, every 5 min): per router with active clients, join
  active+interface, accumulate deltas into the current cycle's `ClientUsage`, refresh the
  `Client` live fields, and mark clients absent from `/ppp/active` offline.
- **FUP check** runs inside the same pass: when cycle usage crosses a stored
  `fup_alert_percents` threshold (× `plan.data_cap_gb`), SMS once per threshold per cycle
  (recorded in `fup_alerted`). This flips the Settings > PPPoE FUP control from
  "pending metering" to live (`fup_metering_ready = true`).

## Where it displays

- **Client detail** (primary): online status, WAN IP, uptime, a usage bar (used / cap / %),
  the down/up split, last-seen.
- **Clients list**: an online dot + "X.X GB this cycle" column.
- **Dashboard tile**: clients online now, total data this month, top consumers, count over
  FUP.

## Build order

1. Adapter: enrich the PPPoE active read to return per-client bytes (join active +
   interface), on base / mikrotik / dummy.
2. Models: `Client` live fields + `ClientUsage`, migration.
3. Metering service: delta accumulation, reset handling, offline marking, live-field
   refresh — source-agnostic so RADIUS can feed the same accumulator later.
4. FUP alert wiring (once per threshold per cycle) + flip `fup_metering_ready`.
5. `poll_pppoe_usage` beat task (5 min) + schedule.
6. API: usage on client detail + list, and a dashboard tile.
7. Frontend: client detail usage panel, list column, dashboard tile.
8. Tests: delta accounting, reset mid-cycle, offline detection, FUP once-per-threshold,
   cycle reset, unreachable-router resilience, tenant isolation.
