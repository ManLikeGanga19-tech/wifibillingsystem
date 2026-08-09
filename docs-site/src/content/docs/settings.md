---
title: Settings
description: Configure your ISP — routers, branding, messaging, billing lifecycle, developer tools and security.
---

Settings is where you configure how your ISP runs. Each panel is safe to leave on its defaults — you only change what you need.

## Routers

Add and manage the gateways at your sites (MikroTik today, more to come). A router can **self-onboard** — it phones home over a secure tunnel — so you don't need a public IP, and CGNAT is no obstacle. You'll see each router's status, hardware, and whether your captive portal reached it.

## Branding

Your **name, logo and colours** on the captive portal your customers see, plus your own **subdomain** (`your-name.wifios.co.ke`).

## PPPoE lifecycle

How your broadband book behaves:

- **Churn** — cancel accounts suspended beyond a threshold (see **[Churn](/churn/)**).
- **Inactive prune** — tidy away long-disabled accounts (off by default).
- **Reminders** — SMS subscribers before their renewal falls due.
- **Invoicing** — auto-issue monthly invoices (on by default) and set your invoice number prefix.

## Messaging

Edit the **SMS/WhatsApp templates** WIFI.OS sends — welcome messages, renewal reminders, suspension notices — so they sound like you. Send bulk messages to your customers.

## Developer

- **API tokens** — for integrating WIFI.OS with your own tools. A token is shown once at creation and stored only as a hash.
- **Webhooks** — get notified when things happen (a subscriber is created, a payment arrives, a ticket opens), with signed delivery.

## Security

- **Change your password.**
- **Two-factor authentication** — an authenticator app. Required to move money, so payouts are always protected.

## Next

- **[Roles & access →](/roles/)**
