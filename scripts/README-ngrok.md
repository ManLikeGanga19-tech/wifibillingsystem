# Keeping M-Pesa callbacks working in dev (ngrok)

Safaricom sends the STK callback to a public URL. On your dev machine that URL is an
ngrok tunnel. Two things make it "just work":

## After a reboot: one command

```bash
./scripts/dev-up.sh
```

Brings up Docker, starts ngrok, points the callback at it, and checks the worker is
healthy. Run it any time payments stop connecting.

## Make the URL permanent (recommended — 2 minutes, once)

By default ngrok's free URL **changes every time ngrok restarts**, so after a reboot the
old URL is dead until you re-run the script. A free **static domain** fixes this for
good — the URL never changes.

1. Go to <https://dashboard.ngrok.com/domains> and click **New Domain**. The free tier
   gives you one, e.g. `calm-otter-1234.ngrok-free.app`.
2. Add it to `.env` in the project root:
   ```
   NGROK_DOMAIN=calm-otter-1234.ngrok-free.app
   ```
3. Run `./scripts/dev-up.sh` once. From now on ngrok always uses that domain, and the
   M-Pesa callback URL never needs changing again — even across reboots.

> On **staging/production** this whole problem disappears: the callback points at your
> real `api.wifios.co.ke`, which never changes. ngrok is a dev-only convenience.

## If a payment still won't connect

```bash
# Is the tunnel alive and reaching the callback?
curl -s http://localhost:4040/api/tunnels | grep public_url

# Is the worker (which provisions the router) up and crash-free?
docker compose ps worker
docker compose logs worker --tail 20
```

A dead worker is the usual culprit — it's what pushes credentials to the router, so if
it's down a paid customer is charged but never connected. `dev-up.sh` checks for this.
