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
5. Once the first deploy finishes, go to the `security-assistant-api`
   service's **Environment** tab and fill in the secrets the Blueprint
   intentionally left blank (`sync: false` in `render.yaml` — these
   aren't something a Blueprint should generate or guess):
   - `OPENAI_API_KEY` (required — the backend won't serve chat without it)
   - `SENTRY_DSN` (optional — leave blank to keep error monitoring off)
6. Redeploy the `api` service once those are set (Render prompts you to).

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
- Any other env var from `api-core/.env.example` you want in production
  (e.g. `LLM_MODEL`, `RATE_LIMIT_LOGIN`) isn't in `render.yaml` — add it
  directly in the dashboard's Environment tab, same as the `sync: false`
  secrets above, rather than hardcoding non-secret config into the
  Blueprint.
