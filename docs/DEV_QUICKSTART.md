# Dev quickstart — the whole system in one command

Everything runs in Docker now: the backend, the workers, the databases, the mailbox, and
all four frontends. `docker compose up` gives you a fully working local system with
nothing to start by hand.

## Start it

```bash
docker compose up -d          # or ./scripts/dev-up.sh (also wires M-Pesa via ngrok)
```

First run pulls images and installs each frontend's dependencies into a named volume —
that takes a few minutes. After that it's seconds.

## What you get

| URL | What |
|---|---|
| http://localhost:4600 | **ISP console** (admin-ui) — the operator's dashboard |
| http://localhost:4700 | **Captive portal** (portal) — what a WiFi customer sees |
| http://localhost:4800 | **Platform Control** (super-admin) — Danamo's own console |
| http://localhost:4900 | **Marketing site** (marketing) — the public site + signup |
| http://localhost:8000 | **API** (Django) |
| http://localhost:8025 | **Mailbox** (Mailpit) — every email the system "sends" |
| localhost:5434 | Postgres (for DBeaver etc.) |

Dev logins are seeded — see the `api` container's startup log (`seed_dev`), e.g. the
platform owner is `254700000000 / admin12345`.

## How the frontends talk to the backend

Each SPA proxies `/api` to Django, so the browser only ever talks to one origin — which
is what makes the httpOnly-cookie auth work with no CORS. On the host that target is
`localhost:8000`; inside Docker it's `http://api:8000` (the compose service name),
selected by `API_PROXY_TARGET` / `API_ORIGIN` in each app's Vite/Astro config.

**Live reload works**: your source is mounted into each container, so editing a file on
the host reloads the browser. Only `node_modules` lives in a container-side named volume
(the host's Windows binaries can't run in a Linux container), so if you add a dependency,
restart that one service: `docker compose restart admin-ui`.

## M-Pesa callbacks (only if testing real payments)

Safaricom needs a public URL to reach your machine. Run `./scripts/dev-up.sh` (it starts
ngrok and points the callback at it), or see `scripts/README-ngrok.md`. Not needed for
UI work.

## Common commands

```bash
docker compose ps                      # what's running
docker compose logs -f admin-ui        # follow one app's logs
docker compose restart worker beat     # after a backend code change to a task
docker compose down                    # stop everything (keeps data)
docker compose down -v                 # stop and wipe the database + volumes
```

> After changing backend **dependencies** (requirements.txt), rebuild:
> `docker compose up -d --build`. Backend Python code hot-reloads (runserver), but the
> Celery **worker/beat do not** — restart them after editing a task.
