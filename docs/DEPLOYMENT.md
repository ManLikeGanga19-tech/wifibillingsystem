# Deployment

One VPS, Docker Compose, Caddy. Not Kubernetes — this runs a pilot and the first paying
ISPs on a ~$25 box, and any engineer you hire can read the whole thing in ten minutes.
When one machine genuinely stops being enough, the move is a second machine and a load
balancer, not a control plane nobody on the team can debug at 3am.

**Staging and production are the same topology.** The only difference is the env file.
That is deliberate: a staging environment that differs structurally from production is a
staging environment that lies to you.

---

## 1. DNS (wifios.co.ke)

| Record | Type | Points to | Why |
|---|---|---|---|
| `wifios.co.ke` | A | server IP | marketing site |
| `www` | A | server IP | |
| `api` | A | server IP | **Safaricom's callbacks are registered against this. It must never move.** |
| `admin` | A | server IP | Platform Control |
| `*` | A | server IP | every ISP: `acme.wifios.co.ke` |

The wildcard is what makes tenancy work — Django reads the tenant from the Host header.

**TLS:** a wildcard certificate cannot be issued over HTTP-01, so Caddy uses a DNS
challenge. Put the domain on Cloudflare (free), mint an API token scoped to **DNS:Edit on
this zone only**, and set `CLOUDFLARE_API_TOKEN`. Nothing else about Cloudflare is
required, and the token grants nothing but DNS records on one zone.

---

## 2. The server

Hetzner CX22 or a DigitalOcean 2GB droplet is enough to start (~$5–25/mo). Ubuntu LTS.

```bash
# Firewall FIRST, before anything is listening.
ufw default deny incoming && ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw enable

# SSH: keys only. Password auth on port 22 is found by a scanner within the hour.
#   /etc/ssh/sshd_config -> PasswordAuthentication no
#                           PermitRootLogin no
systemctl restart ssh

apt install docker.io docker-compose-plugin
```

Unattended security upgrades (`apt install unattended-upgrades`) — the CVEs that get
boxes taken over are almost always old and already patched.

---

## 3. Configure

```bash
git clone <repo> /srv/wifios && cd /srv/wifios
cp deploy/.env.example deploy/.env
# Fill it in. Read the comments — they say which values are unrecoverable if lost.
```

Generate the crypto values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"                                   # DJANGO_SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"      # FIELD_ENCRYPTION_KEY
```

> **`FIELD_ENCRYPTION_KEY` cannot be regenerated.** Lose it and every router password and
> every TOTP seed is unreadable. Keep a copy somewhere that is not this server.

---

## 4. Up

```bash
# Staging — includes Mailpit, so no test email can reach a real ISP.
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env --profile staging up -d

# Production — no Mailpit; EMAIL_HOST points at a real provider.
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d
```

The API container migrates and collects static on boot. Caddy gets certificates on first
request (a minute or two).

**First platform user** — there is no seeded superuser in production:

```bash
docker compose -f deploy/docker-compose.prod.yml exec api python manage.py createsuperuser
```

Then set their `role` to `platform_owner` in Django admin, and **enrol their
authenticator immediately.** That account can see every ISP's money.

---

## 5. Verify before you trust it

```bash
# TLS on a tenant subdomain — this is the whole tenancy model working.
curl -sI https://acme.wifios.co.ke | head -1

# The API is same-origin with the console (this is what makes the cookie work).
curl -s https://acme.wifios.co.ke/api/v1/schema/ -o /dev/null -w '%{http_code}\n'

# Django agrees its own production settings are sane.
docker compose -f deploy/docker-compose.prod.yml exec api python manage.py check --deploy

# The database is NOT reachable from outside. This must FAIL.
nc -zv <server-ip> 5432
```

On staging, read the mail at `http://localhost:8025` **through an SSH tunnel** —
Mailpit is bound to localhost, not published:

```bash
ssh -L 8025:localhost:8025 you@staging
```

---

## 6. The restore drill — do it before you take real money

**A backup you have never restored is not a backup.** Backups fail silently far more
often than they fail loudly, and you find out on the worst day of the year.

```bash
# Take a dump and restore it into a THROWAWAY database.
docker compose -f deploy/docker-compose.prod.yml exec db \
  sh -c 'createdb -U $POSTGRES_USER restore_test'

gunzip -c deploy/backups/wifios-<latest>.sql.gz | \
  docker compose -f deploy/docker-compose.prod.yml exec -T db \
  psql -U wifios -d restore_test

# Now prove it is real: the money must be there.
docker compose -f deploy/docker-compose.prod.yml exec db \
  psql -U wifios -d restore_test -c 'SELECT count(*), sum(amount) FROM billing_ledgerentry;'

docker compose -f deploy/docker-compose.prod.yml exec db \
  sh -c 'dropdb -U $POSTGRES_USER restore_test'
```

Do this on the day you deploy, and again after any migration that changes the shape of a
money table.

**Offsite.** `deploy/backups/` lives on the same disk as the database, which means it
survives a bad migration and *not* a dead server. Sync it somewhere else (`rclone` to
object storage, nightly), and **encrypt it first** — those dumps contain every ISP's
payout account and every customer's phone number.

---

## 7. Deploying a change

```bash
cd /srv/wifios && git pull
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
```

Migrations run automatically on API boot. Rollback is `git checkout <sha> && up -d
--build` — **but a migration that dropped a column does not roll back**, which is why
destructive migrations get a backup taken by hand first.

CI must be green before anything is pulled here. It is not decoration: it runs the tests,
checks for missing migrations, validates the OpenAPI schema, runs Django's own
production-settings audit, and scans for committed secrets.
