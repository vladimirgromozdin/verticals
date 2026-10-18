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
- An Access application for the hostname with one Allow policy (your email), HTTP-only and binding
  cookies, SameSite Lax. Copy its Application Audience (AUD) tag.
- A database migrated to this checkout's version (`python -m verticals.db.runner up`, run with a role
  that may run DDL) and a second role that may only read and write rows, for the container. The
  container never migrates (`VERTICALS_MIGRATE=check`): it refuses to serve a schema it does not match.
- Docker that can build `linux/amd64` images (on an ARM machine, register QEMU first).

## Deploy

```sh
cd deploy/cloudflare
npm ci
cp wrangler.example.jsonc wrangler.jsonc   # git-ignored: your hostname, Access team, AUD, email
printf '{"DATABASE_URL":"postgresql://app_role:…@host:5432/db?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt","VERTICALS_TOKEN":"…"}' > /path/outside/the/repo/secrets.json
npx wrangler deploy --secrets-file /path/outside/the/repo/secrets.json
```

Later deploys need no secrets file: secrets stay with the Worker. Deploy after migrating, from the
same commit every other app on that database runs.
