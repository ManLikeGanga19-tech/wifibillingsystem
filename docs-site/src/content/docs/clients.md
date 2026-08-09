---
title: Clients
description: Manage your broadband subscribers — search, edit, suspend, import and export.
---

The **Clients** page (under PPPoE) is the roster of your broadband subscribers. It shows everyone — active, suspended, and cancelled — so it's the one place to find and manage any line.

## Finding a client

- **Search** by name, phone, account number, or PPPoE username.
- **Filter** by status: `active`, `pending install`, `suspended`, `cancelled`.
- Each row shows their plan, whether they're **online** right now, their **next billing date**, and a "…" menu for actions.

## Everyday actions

From a client's row you can:

- **Edit** every detail (except the permanent account number) — name, phone, plan, router, billing day.
- **Suspend / restore** the line.
- **View or reset** their PPPoE password.
- Open their **details sheet** for the full history.

Changes are pushed to the router as well as saved, so the console and the network never disagree. See **[PPPoE](/pppoe/)** for what happens on a plan or router change.

## Importing existing customers

Two ways to bring customers in without re-typing them:

- **Adopt from the router** — if you already run PPPoE, WIFI.OS reads the logins on your router and lets you import them (it shows which are new, which are already managed, and suggests a plan). Nothing on the router is disturbed.
- **Import a spreadsheet** — migrating from another billing system? Upload a CSV of your customers (names, phones, billing days, plans). Preview it first, then import.

## Exporting

You can download a CSV backup of every client at any time. Passwords are left out by default — including them is a deliberate, owner-only option — so a routine export can't leak your customers' credentials.

## Next

- **[Billing & payments →](/billing-payments/)**
