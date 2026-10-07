# Security Assistant GPT (Lab-Only)

A chat assistant for defensive security work: a FastAPI backend that talks to an
OpenAI-compatible LLM, and a React web console on top of it.

**Lab use only.** The assistant is meant for systems you own or are authorised to
test. The `/exploit/*` endpoints (LLM-generated exploit code) are switched **off** by
default and must stay off on any public deployment (see [DEPLOY.md](DEPLOY.md)).

## What's in it

- **Web console** (`ui-console/`): sign up / log in, streaming chat with a Stop
  button, replies that keep generating if you refresh the page, conversations you can
  rename, delete and pin, projects (folders) and sidebar search.
- **API** (`api-core/`): JWT auth, per-user conversations and projects, rate limiting,
  Alembic-managed SQLite/Postgres schema, structured logging, optional Sentry.
- **Lab CLI** (`api-core/src/cli`): policy-gated static analysis of a repository
  inside the lab scope, with an audit log. Runs `semgrep` and `bandit` (must be on
  your `PATH`); the `osv-scanner` runner is still a placeholder.

```
api-core/        FastAPI backend, Alembic migrations (migrations/), policy config (config/), tests (tests/)
ui-console/      React + TypeScript + Vite frontend
docker-compose.yml   local stack: api + web (+ optional Postgres)
render.yaml      Render Blueprint (see DEPLOY.md)
DEPLOY.md        deployment notes and gotchas
```

## Quick start (local development)

You need Python 3.11+ and Node 22 (what CI and the Docker image use).

**Backend**

```bash
cd api-core
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env`: set a real `OPENAI_API_KEY`. The example file ships placeholder values
(`xxxxxxxxxxxxxxxxxxx`) for `OPENAI_API_KEY`, `OPENAI_ORG_ID` and `OPENAI_BASE_URL`;
replace them with real values, or delete the org and base-URL lines if you use the
default OpenAI endpoint. The API refuses to start without `OPENAI_API_KEY`.

```bash
uvicorn src.api.http:app --reload      # http://127.0.0.1:8000  (docs at /docs in dev)
```

The database is created and migrated automatically on startup (SQLite file at
`api-core/data/app.db` unless you set `DATABASE_URL`).

**Frontend** (in a second terminal)

```bash
cd ui-console
cp .env.example .env                   # VITE_API_BASE_URL=http://127.0.0.1:8000
npm ci
npm run dev                            # http://localhost:5173
```

Open http://localhost:5173, create an account and start chatting.

## Run everything with Docker Compose

```bash
cp api-core/.env.example api-core/.env    # then set OPENAI_API_KEY
docker compose up --build
```

API on http://localhost:8000, web console on http://localhost:3000. The API keeps its
SQLite file in a named volume. To use the bundled Postgres instead, set
`DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/security_assistant`
in `api-core/.env` and run `docker compose up --build postgres api web`.

## Configuration

All backend settings are environment variables (loaded from `api-core/.env` in
development). The ones you are most likely to touch; see
[`api-core/.env.example`](api-core/.env.example) for the full list.

| Variable                                         | Default                                          | Purpose                                                                                                 |
| ------------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY`                                 | – (required)                                     | LLM provider key.                                                                                       |
| `LLM_MODEL` / `OPENAI_DEFAULT_CHAT_MODEL`        | see `.env.example`                               | Chat model name.                                                                                        |
| `OPENAI_BASE_URL`                                | OpenAI                                           | Point at any OpenAI-compatible endpoint (e.g. OpenRouter).                                              |
| `APP_ENV`                                        | `development`                                    | Anything other than `development`/`dev`/`local` makes `JWT_SECRET_KEY` and `CORS_ORIGINS` **required**. |
| `JWT_SECRET_KEY`                                 | dev-only default locally                         | Signs login tokens. Generate: `openssl rand -hex 32`.                                                   |
| `CORS_ORIGINS`                                   | local Vite ports                                 | Comma-separated allowed frontend origins.                                                               |
| `DATABASE_URL`                                   | SQLite file                                      | e.g. `postgresql+psycopg://user:pass@host:5432/db`.                                                     |
| `DB_AUTO_MIGRATE`                                | `1`                                              | Run `alembic upgrade head` on startup; `0` to run it yourself.                                          |
| `RATE_LIMIT_LOGIN`, `_SIGNUP`, `_CHAT`, `_WRITE` | `5/minute`, `5/minute`, `20/minute`, `30/minute` | Per-IP limits (in-memory, per process).                                                                 |
| `TRUSTED_PROXY_HOPS`                             | `0`                                              | Proxies in front of the app; set to `1` on Render so limits are per client.                             |
| `SIGNUP_ENABLED`                                 | `1`                                              | `0` closes registration (existing users can still log in).                                              |
| `ENABLE_DOCS`                                    | on in dev only                                   | Force `/docs`, `/redoc`, `/openapi.json` on (`1`) or off (`0`).                                         |
| `ENABLE_EXPLOIT_ROUTER`                          | `0`                                              | Mounts `/exploit/*`. Keep off outside a private lab.                                                    |
| `SENTRY_DSN`                                     | unset                                            | Enables Sentry error reporting.                                                                         |
| `LOG_LEVEL`, `LOG_FORMAT`                        | `INFO`, `text`                                   | `LOG_FORMAT=json` for log aggregators.                                                                  |

The frontend has one setting, `VITE_API_BASE_URL`. It is baked in **at build time**,
so changing it means rebuilding the frontend, not just restarting it.

## Database migrations (Alembic)

The schema is managed by Alembic (`api-core/migrations/`), not `create_all()`. The API
applies pending migrations on startup (set `DB_AUTO_MIGRATE=0` to disable). Run these
from `api-core/`:

```bash
alembic upgrade head                              # apply all migrations
alembic revision --autogenerate -m "add foo"      # after changing src/db/models.py
alembic check                                     # fail if models and migrations disagree
alembic downgrade -1                              # roll back one step
alembic upgrade head --sql                        # print the SQL instead of running it
```

Always review an autogenerated migration before committing it. Databases created by
the old `create_all()` are adopted automatically: the first `upgrade` skips tables and
columns that already exist.

To check that a database URL really works (migrations plus a write/read round trip):

```bash
cd api-core
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/security_assistant \
  ./scripts/check_db.sh      # needs `pip install -e ".[postgres]"` and `docker compose up -d postgres`
```

## Tests and code quality

```bash
cd api-core
pytest                       # API tests run against throwaway SQLite files
ruff check .
black --check .

cd ../ui-console
npm run lint
npm run format:check
npm run build                # type-check + bundle
```

CI (`.github/workflows/ci.yml`) runs all of the above on every push, plus a Postgres
smoke test. To run the Python and frontend checks automatically before each commit:

```bash
pip install pre-commit && pre-commit install
```

## Deploying

The repo includes a Render Blueprint (`render.yaml`) and Dockerfiles for both
services. Follow [DEPLOY.md](DEPLOY.md), then smoke-test the deployed API:

```bash
cd api-core
python scripts/smoke_test_staging.py https://<your-api>.onrender.com
```

The smoke test signs up, logs in, sends one real chat message (one paid LLM call),
renames and deletes the conversation.

## Lab CLI

```bash
cd api-core
python -m src.cli.cli ./lab/my-repo     # path must be inside config/policies/lab-scopes.yaml
```

The path has to match a prefix listed in `config/policies/lab-scopes.yaml`
(`/tmp/lab/` and `./lab/` by default); anything else is rejected and audit-logged.

## Known limitations

- Rate limits are in memory and per process, so the API runs a single worker. Moving
  the limiter to a shared store (e.g. Redis) is required before scaling out.
- Login tokens are stateless JWTs: there is no server-side logout or revocation.
- `/exploit/*` has no policy-engine check, approval step or dedicated rate limit.
