---
title: Security & sign-in
description: How WIFI.OS keeps your account, your money and your customers' data safe.
---

WIFI.OS protects three things: **your account**, **your money**, and **your customers' data**. Here's how each is kept safe, and what you control.

## Signing in

You sign in with your phone or email and a password. Your session is held securely by the server — nothing sensitive is stored in your browser where a bad extension or a shared computer could reach it. Sign-in attempts are rate-limited and paired with a per-account lockout, so password guessing gets nowhere.

## Two-factor for money

Any action that moves money — a payout, a settlement change — requires a **second factor**: a one-time code from an authenticator app (Google Authenticator, Authy, and the like). This is true for everyone, Owner included. Email proves and notifies your address; the authenticator code is what authorises money. So even if someone got your password, they couldn't move a shilling.

## Roles and least privilege

People see only what their role allows, and the two most sensitive powers — **moving money** and **changing access** — are **Owner-only** and can't be handed out. Remove someone's access and it takes effect on their very next action. See **[Roles & access](/roles/)**.

## Your data is isolated

Your console reaches **only your ISP's** data. There is no screen, filter or link that crosses into another operator's customers, money or routers — the isolation is built into the foundations, not a preference. Customer locations and revenue are sensitive, and they never leave your tenant.

## Platform support access

If you ask Danamo for help and they need to look inside your console, they enter through a **time-boxed, recorded** grant — and while they're in, a loud banner tells you. When it expires, access ends, and the whole session is logged. Platform staff can't wander in uninvited.

## Router credentials

The credentials WIFI.OS uses to control your MikroTik are stored **encrypted** and never displayed back in plain text.

## Next

- Tailor who can do what — **[Roles & access](/roles/)**
- Add and remove staff safely — **[Your team](/team/)**
