---
title: PPPoE (broadband lines)
description: Bill monthly fixed-line subscribers — provisioning, anniversary billing and automatic suspension.
---

PPPoE is for **monthly broadband subscribers** — the home or business you run a cable or wireless link to and bill every month. WIFI.OS manages the whole life of the line: the login on the router, the monthly invoice, and cutting them off if they don't pay.

## Adding a client

Go to **PPPoE → Clients → New client** and fill in:

- **Name, phone** and where they are.
- The **plan** (their monthly package and speed).
- The **router** the line terminates on, and optionally the **tower / access point** for capacity tracking.
- Their **billing day** (1–28) — the day each month their invoice falls due.

WIFI.OS generates a globally-unique **account number** (their permanent M-Pesa reference) and PPPoE **username/password**. Click **Provision** and the login is pushed to the router — the customer can connect.

:::note[The account number is permanent]
It's the reference a customer types into M-Pesa, so it never changes — even if you move them to another router or plan. Everything else is editable.
:::

## Billing and suspension

- On each client's **billing day**, WIFI.OS issues their monthly invoice automatically (anniversary billing).
- When they pay (M-Pesa Paybill using their account number), the invoice is settled and the line stays up.
- If an invoice goes unpaid past its due date, the line is **suspended** — the customer is redirected to a "please pay to reconnect" page. The moment they pay, service is **restored** automatically.

## Changing a line

Editing a client keeps the console **and the router** in agreement:

- Change the **plan** → the new speed is pushed and the session bounced so it takes effect at once.
- Move to another **router** → the login is migrated (created on the new one before it's removed from the old), so the customer is never left with no line.

## Credentials

You can view, set, or reset a client's PPPoE password from their row — useful when an installer needs it on site.

## Bringing existing customers in

Already running PPPoE on your router, or migrating from another billing system? See **[Clients → Importing](/clients/)** — you can adopt the logins already on your router, or import a spreadsheet of customers.

## Next

- **[Plans →](/plans/)**
