# PPPoE suspend → redirect-to-pay

When a broadband client is overdue, the system moves them to the `wifios-suspended`
PPP profile and kicks their session. On reconnect they get limited access and any
web request is redirected to the pay page. Payment (C2B) auto-restores them.

## One-time router setup (per site)

Done automatically for enrolled routers; for hand-configured routers run once. The
platform applies this via the API, but for reference the RouterOS pieces are:

```routeros
# 1. A suspended PPP profile that tags clients into an address-list
/ppp/profile add name=wifios-suspended local-address=<gw> remote-address=<pool> \
    rate-limit=128k/128k address-list=wifios-blocked

# 2. Redirect blocked clients' HTTP to the pay page (the portal /suspended route)
/ip/firewall/nat add chain=dstnat src-address-list=wifios-blocked protocol=tcp \
    dst-port=80 action=dst-nat to-addresses=<PORTAL_IP> to-ports=<PORTAL_PORT> \
    comment=wifios-suspend-redirect

# 3. (production) walled-garden: allow DNS + the portal host for blocked clients,
#    drop the rest, so only the pay page is reachable until they pay.
```

- `<PORTAL_IP>:<PORTAL_PORT>` is the billing portal. LAN pilot: the laptop
  (192.168.2.106:4700). Production: the public portal domain.
- HTTPS cannot be transparently redirected; OS captive-portal detection (which uses
  an HTTP probe) pops the page, and the client can also open any http:// site.

## The pay page

Portal route **`/suspended?router=<id>`** (also accepts `&account=<no>`). It calls:
- `GET /api/v1/pppoe/suspended-notice/?router=<id>[&account=<no>]` — provider +
  paybill + how-to-pay; includes the client's balance/status if the account is known
  (from the query or resolved via the router's live PPPoE session by source IP).
- `GET /api/v1/pppoe/account-lookup/?router=<id>&account=<no>` — the client types
  their account number to see their balance.

## Flow

overdue invoice → `suspend_overdue_clients` beat → `set_pppoe_enabled(False)`
(profile → wifios-suspended, session kicked) → client browses → redirected to
`/suspended` → pays paybill with account number → C2B confirmation →
`record_client_payment` settles invoice → `restore_client` (profile back to plan).
