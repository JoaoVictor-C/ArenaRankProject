# Deploy guide: EC2 (and any other Linux server)

This repo already has a working production topology (`arenarank.lol`): one small
EC2 box running `redis + api + caddy + workers` via **`docker-compose.prod.yml`**,
a database on **AWS RDS** (not in a container), the frontend on **AWS Amplify**,
and **Cloudflare** in front for TLS/DNS. That layout is documented at the top of
`docker-compose.prod.yml` — read it first.

This guide covers two paths:

- **Path A — reproduce the current prod topology** (new EC2 box, external managed
  Postgres, Cloudflare). Use this for a second EC2 box (failover, staging) or if
  you're rebuilding the existing one from scratch.
- **Path B — generic single-box deploy** (any VPS: EC2, Lightsail, Hetzner,
  DigitalOcean...) using the full `docker-compose.yml`, which runs Postgres +
  PgBouncer + Redis + API + workers + frontend all in containers. Use this when
  you don't have (or don't want) a separate managed database.

Both paths share steps 1–4 (server prep, Docker, git, code on the box).

---

## 1. Launch the server

### EC2 (Path A, matching current prod)

- AMI: **Ubuntu 22.04 LTS** (or 24.04), x86_64.
- Instance type: `t3.micro` is what prod runs on today (redis + api + caddy +
  3 trimmed workers fit in ~908 MB with headroom). Go `t3.small` if you'll also
  run local Postgres (Path B) or the full worker set.
- Storage: 20–30 GB gp3 is plenty (no DB data on this box in Path A).
- Security group — inbound:| Port                                                                          | Source                                  | Why                    |
  | ----------------------------------------------------------------------------- | --------------------------------------- | ---------------------- |
  | 22                                                                            | your IP only (not`0.0.0.0/0`)         | SSH                    |
  | 80                                                                            | `0.0.0.0/0` (or Cloudflare IP ranges) | HTTP → redirects/ACME |
  | 443                                                                           | `0.0.0.0/0` (or Cloudflare IP ranges) | HTTPS (Caddy)          |
  | Do**not** open 8000 (API), 5432/6432/6433 (Postgres/PgBouncer), or 6379 |                                         |                        |
  | (Redis) — those stay internal to the Docker network.                         |                                         |                        |
- Key pair: create/download a `.pem`, this is your SSH credential.
- Elastic IP: allocate and associate one so the server's IP doesn't change on
  stop/start (DNS/Cloudflare points at this).

### Any other server (Path B)

Same idea, minus AWS specifics: Ubuntu 22.04/24.04, a public IPv4, and a
firewall that only allows 22/80/443 in. If the provider doesn't have a
security-group concept, use `ufw` (see step 3).

---

## 2. First login and basic hardening

```bash
# from your machine
ssh -i /path/to/key.pem ubuntu@<server-ip>        # EC2 default user is "ubuntu"
# generic VPS: ssh root@<server-ip>, then create a sudo user and stop using root
```

```bash
# on the server
sudo apt update && sudo apt upgrade -y
sudo timedatectl set-timezone UTC

# firewall (skip on EC2 if you're relying purely on the security group — but
# defense in depth is cheap, and it's required on non-AWS hosts)
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 3. Install git, Docker, and the Compose plugin

```bash
sudo apt install -y git ca-certificates curl gnupg

# Docker's official install script (works on any Debian/Ubuntu derivative)
curl -fsSL https://get.docker.com | sudo sh

# run docker without sudo
sudo usermod -aG docker $USER
newgrp docker          # or log out/in for the group change to take effect

# verify
docker version
docker compose version
```

Make sure Docker starts on boot (the install script normally does this, but
confirm):

```bash
sudo systemctl enable --now docker
```

---

## 4. Get the code onto the server

The GitHub repo (`JoaoVictor-C/ArenaRankProject`) — check whether it's public
or private first (`gh repo view JoaoVictor-C/ArenaRankProject` from your own
machine, or just try the clone below).

**If public**, plain HTTPS clone works:

```bash
git clone https://github.com/JoaoVictor-C/ArenaRankProject.git ~/arenarank
cd ~/arenarank
```

**If private**, don't put a personal password/PAT in the clone URL long-term.
Use a fine-grained **deploy key** (read-only, repo-scoped) instead:

```bash
# on the server, as the deploy user
ssh-keygen -t ed25519 -C "ec2-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Copy that public key into **GitHub → repo → Settings → Deploy keys → Add deploy
key** (read-only is enough). Then:

```bash
git clone git@github.com:JoaoVictor-C/ArenaRankProject.git ~/arenarank
cd ~/arenarank
```

Never commit `.env`, `.env.prod`, or `*.dump` — `.gitignore` already excludes
them (checked: `.env`, `.env.*`, `**/.env*`, `*.dump` are all ignored, only
`*.env.example` is tracked). That means **secrets never come from git** — you
copy them onto the box separately (next step).

---

## 5. Configure secrets (`.env`)

Both compose files read a sibling `.env` via `env_file: [.env]`. Create it on
the server — never by committing it:

```bash
cd ~/arenarank
cp backend/.env.example .env     # start from the template, then edit
nano .env
```

Fill in at minimum (see `backend/.env.example` for the full/annotated list):

- `DATABASE_URL` — `postgresql+asyncpg://user:pass@host:5432/arena`
  (Path A: your RDS endpoint. Path B: `postgres` service name inside compose.)
- `REDIS_URL` — compose sets this per-service already (`redis://redis:6379/0`);
  you generally don't need to set it in `.env`.
- `RIOT_API_KEY` — from the Riot developer portal (use a **production** key,
  not a 24h dev key, for a long-running ingestion pipeline).
- `ADMIN_API_KEY` — any long random string (`openssl rand -hex 24`). The API
  fails closed (503 on all `/admin/*`) until this is set — that's intentional.
- `ENVIRONMENT=production`, `LOG_LEVEL=INFO`.
- `CORS_ORIGINS` — your frontend origin(s).

Lock the file down:

```bash
chmod 600 .env
```

**Transferring secrets safely**: if you already have a working `.env`/`.env.prod`
locally (as this repo does), copy it directly instead of retyping — don't paste
secrets through chat/Slack:

```powershell
# from Windows, using scp (ships with modern Windows/PowerShell)
scp -i C:\path\to\key.pem .env.prod ubuntu@<server-ip>:~/arenarank/.env
```

---

## 6A. Path A — reproduce current prod (external DB, Cloudflare)

This is exactly what `docker-compose.prod.yml` (== `docker-compose.prod-ec2.yml`,
they're identical today) runs: `redis`, `api`, `caddy`, `worker-sweep`,
`worker-standard`, `worker-priority`, `scheduler`. No local Postgres —
`DATABASE_URL` in `.env` must point at a reachable managed Postgres (RDS or
otherwise).

1. **Provision the database** (if you don't already have one): AWS RDS
   Postgres 16+ (the app expects TimescaleDB features — RDS's Timescale
   extension support varies by region/version, confirm before committing, or
   use a Timescale-flavored host). Note the endpoint, user, password, db name
   into `DATABASE_URL`.
2. **Edit `Caddyfile`** — change `api.arenarank.lol` to your domain, or leave
   it if reusing the same domain on a second box:
   ```
   your-api-domain.example {
       tls internal
       encode gzip
       reverse_proxy api:8000
   }
   ```

   `tls internal` is used because Cloudflare (SSL mode "Full") intercepts
   HTTP-01/TLS-ALPN, so public ACME can't validate here. **If you are not
   fronting with Cloudflare**, replace `tls internal` with your real domain and
   let Caddy handle Let's Encrypt automatically (remove that line — plain
   `your-domain.example { reverse_proxy api:8000 }` is enough).
3. **Bring the stack up**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
4. **Migrate + (optionally) seed** — migrations must target the direct
   Postgres port (5432), not a pooler:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
   docker compose -f docker-compose.prod.yml run --rm api python -m arena.db.seed   # only on a fresh DB
   ```
5. **DNS**: point `api.<yourdomain>` at the box's Elastic IP (A record in
   Cloudflare, orange-cloud/proxied if you want CF's TLS+CDN in front).
6. **Frontend**: prod deploys the React app separately via AWS Amplify (not on
   this box). Point Amplify's build at `frontend/`, set `VITE_API_URL` (check
   `frontend/.env.production` / `frontend/.env.example` for the exact var name)
   to `https://api.<yourdomain>`.

---

## 6B. Path B — generic single-box deploy (self-contained)

Use the full `docker-compose.yml` — it includes Postgres/TimescaleDB,
PgBouncer (both pool modes), Redis, API, the full worker set, and even a dev
frontend container + Adminer. Good for a standalone server with no external
managed DB.

```bash
cd ~/arenarank
docker compose up -d --build
```

Then migrate/seed the same way, but against the compose `migrate`/`seed`
services (check exact service names in `docker-compose.yml` — they're already
defined: `migrate`, `seed`):

```bash
docker compose run --rm migrate
docker compose run --rm seed
```

For production use on Path B, you'd still want a reverse proxy (Caddy or
nginx) terminating TLS in front of the `api` container — copy the `caddy`
service block from `docker-compose.prod.yml` into your compose file, or run
Caddy/nginx as a separate host-level service. Don't expose Postgres/Redis/API
ports publicly — same rule as Path A.

---

## 7. Verify it's actually working

```bash
docker compose -f docker-compose.prod.yml ps           # all services "healthy"/"running"
docker compose -f docker-compose.prod.yml logs -f api   # tail logs, ctrl-C to stop
curl -s http://localhost:8000/healthz | head            # from inside the box (bypasses proxy)
curl -s https://api.<yourdomain>/healthz                # from outside (through Caddy/Cloudflare)
```

---

## 8. Ongoing operations

**Deploying a new version:**

```bash
cd ~/arenarank
git pull
docker compose -f docker-compose.prod.yml up -d --build   # rebuilds only changed images
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head   # if new migrations
docker compose -f docker-compose.prod.yml exec redis redis-cli FLUSHALL       # backend/rating changes don't auto-invalidate cache
```

That last step matters — per this repo's own gotchas doc (`workaround.md` §4),
a uvicorn/container restart does **not** invalidate the Redis leaderboard
cache. Flush it after any rating/service change or the site will keep serving
stale data.

**Restart policy**: every service in both compose files sets
`restart: unless-stopped`, so containers survive a Docker daemon restart or
server reboot automatically, as long as `docker.service` itself is enabled
(`systemctl enable docker`, done in step 3).

**Backups**:

- Path A (RDS): use RDS automated snapshots (enable in the AWS console) rather
  than manual `pg_dump` for your primary backup strategy.
- Path B (local Postgres container with a named `pgdata` volume): schedule
  `docker compose exec postgres pg_dump -U arena arena > backup.sql` via cron,
  and copy it off-box (S3, etc.) — a Docker volume alone is not a backup.

**Secrets rotation**: if a key in `.env` (Riot API key, `ADMIN_API_KEY`, DB
password) ever leaks, rotate it at the source (Riot dev portal / RDS console),
update `.env`, then `docker compose up -d` to restart with the new value —
no rebuild needed for env-only changes.

---

## Security checklist (before calling it "done")

- [ ] SSH restricted to your IP (or a bastion), key-only auth (`PasswordAuthentication no` in `sshd_config`)
- [ ] Only 22/80/443 reachable from the internet; DB/Redis/API ports stay internal
- [ ] `.env` is `chmod 600`, never committed, never pasted into logs/tickets
- [ ] `ADMIN_API_KEY` is set (the API 503s on `/admin/*` otherwise — that's the fail-closed design, don't "fix" it by weakening it)
- [ ] `ufw` (or the cloud security group) enabled
- [ ] Automatic OS security updates on (`sudo apt install unattended-upgrades`)
- [ ] Elastic/static IP so DNS doesn't drift
- [ ] A tested restore path for backups (Path A: verify an RDS snapshot restore; Path B: verify `pg_dump`/restore actually round-trips)
