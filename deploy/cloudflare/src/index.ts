// The hosted board: Cloudflare Access signs the owner in, this Worker checks that signature again and
// forwards to one container running the repository's Dockerfile, which talks to the database.
import { Container } from '@cloudflare/containers'
import { createRemoteJWKSet, jwtVerify } from 'jose'

export interface Env {
  BOARD: DurableObjectNamespace<Board>
  // Plain vars (wrangler.jsonc): which Access application, and whose board.
  ACCESS_TEAM_DOMAIN: string // https://<team>.cloudflareaccess.com
  ACCESS_AUD: string
  OWNER_EMAIL: string
  // Secrets (`wrangler secret put`): never in the config file or the bundle.
  DATABASE_URL: string
  VERTICALS_TOKEN: string
}

export class Board extends Container<Env> {
  defaultPort = 80
  sleepAfter = '15m'

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env)
    this.envVars = {
      VERTICALS_DATABASE_URL: env.DATABASE_URL,
      VERTICALS_TOKEN: env.VERTICALS_TOKEN,
      VERTICALS_OWNER: 'local',
      // The role here may not run DDL: migrations happen from a workstation, this only checks.
      VERTICALS_MIGRATE: 'check',
      VERTICALS_SEED_SAMPLE: '0',
      // Sources read files on the owner's own machine; that machine runs them.
      VERTICALS_SOURCES_TICK: '0',
      VERTICALS_POOL_MIN: '1',
      VERTICALS_POOL_MAX: '5',
      // Agents reach the board at /mcp, signed in through Access's OAuth.
      VERTICALS_MCP_HTTP: '1',
    }
  }

  private ready = false

  override onStop(): void {
    this.ready = false
  }

  override async fetch(request: Request): Promise<Response> {
    const headers = new Headers(request.headers)
    headers.delete('cf-container-target-port') // the board listens on one port, never a caller's choice
    if (!this.ready) {
      // A cold start waits for the database and then the API; give it more than the SDK's default.
      await this.startAndWaitForPorts({ ports: 80, cancellationOptions: { portReadyTimeoutMS: 90_000 } })
      for (let attempt = 0; attempt < 120 && !this.ready; attempt++) {
        const health = await this.containerFetch('http://board/healthz', {}, 80).catch(() => null)
        if (health?.ok) this.ready = true
        else await new Promise((resolve) => setTimeout(resolve, 500))
      }
      if (!this.ready) return new Response('The board did not start in time', { status: 503 })
    }
    return super.fetch(new Request(request, { headers }))
  }
}

const SECURITY_HEADERS: Record<string, string> = {
  'Strict-Transport-Security': 'max-age=31536000',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'same-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Content-Security-Policy': [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; '),
}

let jwks: ReturnType<typeof createRemoteJWKSet> | undefined

async function isOwner(request: Request, env: Env): Promise<boolean> {
  const token = request.headers.get('Cf-Access-Jwt-Assertion')
  if (!token) return false
  jwks ??= createRemoteJWKSet(new URL(`${env.ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs`))
  try {
    const { payload } = await jwtVerify(token, jwks, {
      issuer: env.ACCESS_TEAM_DOMAIN,
      audience: env.ACCESS_AUD,
      algorithms: ['RS256'],
    })
    return typeof payload.email === 'string' && payload.email.toLowerCase() === env.OWNER_EMAIL.toLowerCase()
  } catch {
    return false
  }
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

// Access lets the browser send its cookie on cross-site requests too, and nginx adds the API key to
// whatever arrives, so a change signed in by that cookie must come from a page on this very origin.
// An agent signs in with an OAuth token instead, which no other site can make a browser send.
function sameOrigin(request: Request, url: URL): boolean {
  if (SAFE_METHODS.has(request.method)) return true
  if (!/(^|;\s*)CF_Authorization=/.test(request.headers.get('Cookie') ?? '')) return true
  return request.headers.get('Origin') === url.origin
}

function secured(response: Response, path: string): Response {
  const out = new Response(response.body, response)
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) out.headers.set(name, value)
  if (path.startsWith('/api') || path.startsWith('/mcp') || path === '/healthz') out.headers.set('Cache-Control', 'no-store')
  return out
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!(await isOwner(request, env))) return new Response('Forbidden', { status: 403 })
    const url = new URL(request.url)
    if (!sameOrigin(request, url)) return new Response('Cross-origin change refused', { status: 403 })

    // The app authenticates nothing by cookie or header itself: nginx in the container adds the API key.
    const headers = new Headers(request.headers)
    for (const name of [...headers.keys()]) {
      if (name.startsWith('cf-access-') || name === 'authorization' || name === 'cookie') headers.delete(name)
    }

    const response = await env.BOARD.getByName('board').fetch(new Request(request, { headers }))
    return secured(response, url.pathname)
  },

  // The cron in wrangler.jsonc keeps the container awake, so a visit never waits for it to boot. It asks nginx for the
  // page, which reads no database: the database can still sleep between real uses.
  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    await env.BOARD.getByName('board').fetch(new Request('http://board/'))
  },
} satisfies ExportedHandler<Env>
