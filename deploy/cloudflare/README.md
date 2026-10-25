# Hosting the board on Cloudflare

One person's board on their own subdomain, behind a Google (or one-time PIN) login:

```
browser → Cloudflare Access (only the owner's email) → this Worker (checks Access's signed token
again, refuses cross-origin changes, strips credentials) → one Cloudflare Container running the
repository's Dockerfile (nginx adds the API key, the API listens on loopback) → PostgreSQL
```

The container has no public address: only this Worker reaches it. The in-app agent chat and Sources
are not part of the hosted board; they run in the local or desktop app against the same database.

## Before the first deploy

- Workers Paid (Containers need it) and a zone on Cloudflare for the hostname.
- An Access application for the hostname with one Allow policy (your email), HTTP-only cookies,
  SameSite Lax (a binding cookie breaks agent sign-in, see Agents). Copy its Application Audience (AUD) tag.
- A database migrated to this checkout's version (`python -m verticals.db.runner up`, run with a role
  that may run DDL) and a second role that may only read and write rows, for the container. The
  container never migrates (`VERTICALS_MIGRATE=check`): it refuses to serve a schema it does not match.
- Docker that can build `linux/amd64` images (on an ARM machine, register QEMU first).

## Deploy

```sh
cd deploy/cloudflare
npm ci
cp wrangler.example.jsonc wrangler.jsonc   # git-ignored: your hostname, Access team, AUD, email
printf '{"DATABASE_URL":"postgresql://app_role:…@host:5432/db?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt&keepalives=1&keepalives_idle=60&keepalives_interval=10&keepalives_count=3","VERTICALS_TOKEN":"…"}' > /path/outside/the/repo/secrets.json
npx wrangler deploy --secrets-file /path/outside/the/repo/secrets.json
```

Later deploys need no secrets file: secrets stay with the Worker. Run `./deploy.sh` instead of
`npx wrangler deploy`: it deploys only the `deploy` branch, with no local changes, and only when it matches
the branch on GitHub. Deploy after migrating, from the same commit every other app on that database runs.

## Agents

The container also serves the board's MCP tools at `/mcp`. An agent signs in through Access's
OAuth: turn on Managed OAuth in the Access application's advanced settings and allow the redirect
addresses of the clients you use (`https://claude.ai/api/mcp/auth_callback` for Claude, localhost
for Claude Code and Codex), and leave the binding cookie off: Access rejects every OAuth token while
it is on. Then add `https://<your hostname>/mcp` as a remote MCP server in the
client and sign in with the same account. The Worker checks the token Access forwards exactly as it
does for the browser; the same-origin rule applies only to requests signed in by Access's cookie.

## What it costs

Memory and disk are billed for every hour the container runs, at the instance type's full size; CPU only as used.
The cron in `wrangler.example.jsonc` pings the container every 10 minutes, so it never sleeps and a visit never waits for
it to boot: on `lite` that is about $1.70 a month on top of Workers Paid, on `basic` about $7. The ping reads no
database, so a database that scales to zero still sleeps between real uses; a page hidden for a minute closes its live
stream for the same reason. Without the cron the container sleeps 15 minutes after the last request and the next visit
waits for it to boot. The `keepalives` settings in the database URL let a connection that died silently fail within
about 90 seconds instead of holding the live stream open with nothing behind it.
