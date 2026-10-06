# Deploying to Render

`render.yaml` at the repo root defines three resources: the `api-core`
backend, the `ui-console` frontend, and a managed Postgres database. Most
of the wiring between them is automatic; this doc covers the parts that
aren't (and can't be, from a YAML file).

## First-time setup

1. Push `render.yaml` to `main` (or whichever branch you'll deploy from).
2. In the [Render dashboard](https://dashboard.render.com): **New +** →
   **Blueprint** → select this repo. Render reads `render.yaml` and shows
   you a preview of what it's about to create.
3. **Service names are public subdomains.** `security-assistant-api` and
   `security-assistant-web` become `https://security-assistant-api.onrender.com`
   etc. — these must be globally unique across *all* Render users. If
   either name is taken, Render will ask you to change it; if you do,
   update the matching `CORS_ORIGINS` / `VITE_API_BASE_URL` values in
   `render.yaml` to match and push again, since they're hardcoded to
   each other's predictable URL (Render Blueprints have no "give me
   this other service's public URL with https://" primitive — only
   internal hostnames without a scheme — so the two names have to be
   kept in sync by hand).
4. Click **Apply**. Render provisions the database first, then builds
   and deploys both Docker services.
5. The Blueprint intentionally leaves two secrets blank (`sync: false` in
   `render.yaml` — these aren't something a Blueprint should generate or
   guess). Render asks for them when you apply a Blueprint for the first
   time, so **enter `OPENAI_API_KEY` right then**:
   - `OPENAI_API_KEY` (required — the api refuses to start without it, so
     if you skip it the first deploy shows as *failed* and restarts in a
     loop until you add it)
   - `SENTRY_DSN` (optional — leave blank to keep error monitoring off)
6. If you skipped either, add it in the `security-assistant-api`
   service's **Environment** tab and redeploy the api service.

## Things worth knowing before you rely on this for real

- **Free Postgres expires after 30 days**, then a 14-day grace period,
  then it's deleted — data included. Fine for an initial staging check;
  set a reminder, or upgrade the database to the smallest paid plan
  (~$6/mo) before you'd actually miss the data.
- **Free web services sleep after 15 minutes idle** and take ~30-60s to
  wake on the next request. Your first staging smoke test of the day
  will look like a hang, not a bug — the Postgres and Dockerize work
  is fine. Upgrade to the $7/mo instance plan to remove this if a
  cold start would be confusing during the Task 5 smoke test.
- **`DB_AUTO_MIGRATE` defaults to on** (see `api-core/.env.example`), so
  the api service runs `alembic upgrade head` on every boot — no manual
  migration step needed after you push schema changes.
- **CORS_ORIGINS / VITE_API_BASE_URL are hardcoded to each other's URL**
  in `render.yaml` (see step 3 above). If you later add a custom domain,
  update both and push.
- **Rate limits need `TRUSTED_PROXY_HOPS` behind Render.** The api only
  ever sees Render's proxy as the connecting address, so without it every
  user shares one bucket (5 logins/minute for the whole site). The
  Blueprint sets it to `1`: the client IP is the last `X-Forwarded-For`
  entry, which Render's own proxy appends. Never read the first entry --
  clients can forge it and get a fresh bucket per request. Too low only
  makes buckets coarser; too high makes the key forgeable, so raise it
  only after checking on staging:
  1. From one machine send 6 bad logins, each with a different forged
     header; the 6th must be `429`:
     `for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w "%{http_code}\n" -X POST https://security-assistant-api.onrender.com/auth/login -H "Content-Type: application/json" -H "X-Forwarded-For: 9.9.9.$i" -d '{"email":"a@example.com","password":"wrong-password-1"}'; done`
     If you never see `429`, the key is forgeable: set `TRUSTED_PROXY_HOPS`
     back to `1` (or `0`).
  2. Right after, send one login from a different network (e.g. phone on
     mobile data). It must not be `429`; if it is, the bucket is too
     coarse (Cloudflare edge shared) and you may try `2`, then repeat step 1.
- **`ENABLE_EXPLOIT_ROUTER` stays `"0"` here on purpose.** `/exploit/*`
  asks the LLM to generate working exploit code and run instructions for
  an arbitrary target; today it's reachable by any authenticated user,
  with no `PolicyEngine` check, no human-approval step, and no rate limit
  of its own. Until that's built, this flag is the only thing stopping
  it from being a public, unguarded exploit generator on
  `security-assistant-api.onrender.com`. Don't flip it to `"1"` here.
  If you need it, run it locally (`ENABLE_EXPLOIT_ROUTER=1` in your
  `.env`) where only you can reach it.
- **API docs are off in production.** `/docs`, `/redoc` and
  `/openapi.json` only exist when `APP_ENV` is `development`/`dev`/`local`
  (they'd publish a map of every route). Set `ENABLE_DOCS=1` in the
  dashboard if you really want them on a deploy.
- **Signup is open by default**, and every chat is a paid OpenAI call, so
  the rate limits are the only thing between a stranger and your API bill.
  Once your own account (and any you want to invite) exist, set
  `SIGNUP_ENABLED=0` in the dashboard and redeploy: signups then return
  403 while existing users keep logging in. Check usage limits on your
  OpenAI account either way.
- Any other env var from `api-core/.env.example` you want in production
  (e.g. `LLM_MODEL`, `RATE_LIMIT_LOGIN`) isn't in `render.yaml` — add it
  directly in the dashboard's Environment tab, same as the `sync: false`
  secrets above, rather than hardcoding non-secret config into the
  Blueprint.
