# MikroTik Setup — Connect a Real Router

Goal: a customer joins your WiFi → gets the captive portal → pays via M-Pesa or
voucher → the backend provisions them on the router → they're online, and cut off
automatically at expiry.

## Prerequisites (check these first)

1. **RouterOS v7.1 or newer** — the REST API does not exist on v6.
   Check: `/system resource print` (look at `version`). Upgrade: `/system package update install`.
2. The router has a **hotspot-capable interface** (the WLAN or a bridge your clients join).
3. For the pilot, your laptop (running Docker) is **connected to the router's LAN**
   so both can reach each other. Production replaces this with a WireGuard tunnel
   to the cloud server — that comes in the deployment phase.

Throughout, replace:
| Placeholder | Meaning | Example |
|---|---|---|
| `LAPTOP_IP` | Your laptop's IP on the router's LAN | `192.168.88.50` |
| `HOTSPOT_IF` | Interface/bridge clients connect to | `bridge` or `wlan1` |

Find your laptop IP: `ipconfig` → the adapter connected to the MikroTik network.

## Step 1 — API user + enable REST (paste in MikroTik terminal)

```routeros
/user group add name=billing-api policy=read,write,api,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!password,!sensitive
/user add name=wifios group=billing-api password=CHANGE-ME-STRONG
# REST API rides on the web service. For LAN pilot, plain www is acceptable;
# production should use www-ssl with a certificate.
/ip service set www disabled=no port=80
```

## Step 2 — Hotspot server (skip pieces you already have)

```routeros
/ip pool add name=hs-pool ranges=10.5.50.10-10.5.50.254
/ip dhcp-server add name=hs-dhcp interface=HOTSPOT_IF address-pool=hs-pool disabled=no
/ip address add address=10.5.50.1/24 interface=HOTSPOT_IF
/ip dhcp-server network add address=10.5.50.0/24 gateway=10.5.50.1 dns-server=8.8.8.8
/ip hotspot profile add name=wifios-hs hotspot-address=10.5.50.1 dns-name=wifi.local login-by=http-pap,http-chap
/ip hotspot add name=hotspot1 interface=HOTSPOT_IF address-pool=hs-pool profile=wifios-hs disabled=no
```

## Step 3 — Speed profiles matching your plans

The backend sets each hotspot user's `profile` to the plan's `mikrotik_profile`
field. Create one profile per speed tier (rate-limit is upload/download):

```routeros
/ip hotspot user profile add name=default rate-limit=2M/5M shared-users=1
/ip hotspot user profile add name=plan-premium rate-limit=3M/6M shared-users=2
/ip hotspot user profile add name=plan-home rate-limit=5M/10M shared-users=3
```

Then in the admin UI (Packages) or Django admin, set each plan's
**mikrotik_profile** to the matching name. Plans using `default` need no change.

## Step 4 — Walled garden (what customers can reach BEFORE paying)

```routeros
/ip hotspot walled-garden ip add action=accept dst-host=LAPTOP_IP comment="billing portal + API"
```

That's all the pilot needs (the portal and API are both on your laptop; the
M-Pesa conversation happens server-side, not from the customer's phone browser).

## Step 5 — Login page that redirects to the portal

The hotspot's login page must send unauthenticated users to the captive portal
with the device context. On the router, replace `hotspot/login.html` (Files →
edit, or upload via FTP/Winbox) with:

```html
<html><head>
<meta http-equiv="refresh" content="0; url=http://LAPTOP_IP:4700/?mac=$(mac-esc)&ip=$(ip)&login=$(link-login-only-esc)&orig=$(link-orig-esc)&router=ROUTER_ID">
</head><body>Redirecting to payment page…</body></html>
```

`ROUTER_ID` is the numeric ID shown after Step 6 (usually `1` for your first router).
After paying, the portal auto-POSTs the hotspot credentials back to
`$(link-login-only)` — the customer never types anything.

## Step 6 — Register the router in the console

Admin UI → **Devices → MikroTik → Add Router**:
- Site name: e.g. `Site A`
- Management IP: the router's LAN IP your laptop can reach (e.g. `192.168.88.1`)
- API port: `80`, **Use TLS: off** (pilot; production uses 443 + www-ssl)
- Username `wifios`, the password from Step 1
- Backend: **MikroTik RouterOS v7 REST**

Click **Test connection** — it must go green/online.

## Step 7 — End-to-end test checklist

1. Phone joins the hotspot WiFi → captive portal appears with your plans.
2. Buy the cheapest plan with a real Safaricom number (sandbox = no money moves).
3. Enter M-Pesa PIN → portal shows "Payment received" → auto-connects.
4. On the router: `/ip hotspot user print` shows the phone number;
   `/ip hotspot active print` shows the live session with `limit-uptime` counting down.
5. Console → Users → Active Users shows the session; Suspend kicks it instantly.
6. Wait for expiry (or set a 5-minute test plan): the user is cut off by the
   router's own `limit-uptime` AND swept by the server — belt and braces.
7. Voucher path: generate a batch, redeem a code on the portal, confirm login.

## Production notes (deployment phase)

- Switch `www` off, `www-ssl` on with a certificate; router record: port 443 + TLS.
- WireGuard: the router dials the cloud server; `management_host` becomes the
  tunnel IP (e.g. `10.10.0.2`). Script will be generated during deployment.
- Walled garden then allows your real domain instead of `LAPTOP_IP`.
