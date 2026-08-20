---
title: Developer & API
description: Automate and integrate WIFI.OS with API tokens scoped to your ISP.
---

If you want to build on top of WIFI.OS — a custom dashboard, an integration with another tool, your own automation — the **Developer** settings give you API access scoped to your own ISP.

## API tokens

Create an **API token** from **Settings → Developer**. A token authenticates as your ISP and reaches only your ISP's data, exactly like a person's login is scoped to one tenant. Treat a token like a password:

- Give each integration its **own** token, so you can revoke one without breaking the others.
- **Revoke** a token the moment it's no longer needed or might be exposed — it stops working immediately.
- A token is shown once when created; store it somewhere safe, because it can't be shown again.

## What you can do with it

The API mirrors what the console does — read customers and payments, create and update records, trigger actions — so anything you do by hand you can automate. The full, always-current API reference is generated from the system itself, so it never drifts from what the platform actually accepts.

## Safe by design

API access respects the same rules as the console: your token can't reach another operator's data, money actions still carry their protections, and requests are rate-limited so a runaway script can't overwhelm the system. Automation gets the same guardrails as a person.

## Next

- How access and money are protected — **[Security & sign-in](/security/)**
- Everything in Settings — **[Settings](/settings/)**
