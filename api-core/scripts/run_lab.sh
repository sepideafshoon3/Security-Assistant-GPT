#!/usr/bin/env bash
# Serve the API on all interfaces, e.g. on a lab machine other hosts can reach.
#
# APP_ENV=lab is deliberately NOT a local-dev environment, so the app refuses to
# start without JWT_SECRET_KEY and CORS_ORIGINS (set them in api-core/.env or
# the environment). Override the port with APP_PORT=9000.
set -euo pipefail

export APP_ENV=lab

uvicorn src.api.http:app --host 0.0.0.0 --port "${APP_PORT:-8000}"
