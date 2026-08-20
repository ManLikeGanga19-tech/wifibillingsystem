---
title: Fibre plant & routing
description: Map your fibre outside plant, track port capacity, see a fault's blast radius, and trace the shortest cable route.
---

If you run fibre — on its own or alongside radio — WIFI.OS models your **outside plant** as a real network: the physical points and the cables between them. That gives you live capacity, instant fault impact, and the shortest cable route between any two places.

## Points and spans

Your plant is made of two things:

- **Points** — the physical nodes: your **OLT/POP**, **splitters**, **cabinets**, **ODPs** (the boxes customers drop off), plus **poles**, **closures** and **handholes**.
- **Spans** — the cables that run between two points, with a cable type and a run length in metres.

Lay them from the **Fibre Plant** screen, or drop them straight onto the **[map](/map/)**. A hybrid ISP uses fibre points for its fibre customers and access points for its radio customers — both live on the same map.

## Port capacity, counted live

Points that carry customer drops — ODPs, splitters and cabinets — show **used** and **free** capacity. This is never a number you maintain by hand: *used* is counted from reality (customers dropped on an ODP, downstream cables on a splitter), so it can't drift. An ODP with 16 ports and 11 customers simply shows **5 free**.

## Blast radius — who a fault takes offline

Click any point and choose **affected** to see the **blast radius**: every customer that a fault there would take offline — that point plus everything downstream of it. When a splitter fails, you see the exact list of customers affected, not a guess. This is the payoff of attaching each fibre customer to their ODP.

## Shortest cable route

Turn on **Route** on the map to trace the **shortest cable path** through your own plant between any two points — the cable route, not the road. It answers questions a driving app can't:

- The cheapest fibre run to reach a new customer from your nearest splitter.
- The exact route, total metres and number of splices to a specific customer.
- Which point feeds an ODP, and how far.

**How to use it:**

1. On the map, click **Route**.
2. Pick a **start** — *"Start from my location"* (your GPS snaps onto the nearest plant point), or click a fibre point or a client.
3. Click the **destination** — a fibre point or a customer.

The shortest path lights up, with **total distance, number of spans, and splice count**. If two points have no cable between them, it tells you plainly — *"No cable path connects those two points."* Fill in each span's **length** for exact distances; where a length is blank, the route falls back to the straight-line distance so it always has a sensible figure.

Routing works for **any role** that can see the map — including a technician standing in the field — so the person doing the work can trace the run from where they are.

## Deletes are safe

Removing a point or span is a **soft delete**: plant that took a crew a day to record is never one click from gone. It's hidden but recoverable, and you can restore it.
