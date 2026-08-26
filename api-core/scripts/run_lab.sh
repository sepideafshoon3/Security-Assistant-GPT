#!/usr/bin/env bash
set -euo pipefail

export APP_ENV=lab
export APP_PORT=8000

uvicorn src.api.http:app --host 0.0.0.0 --port "${APP_PORT}"
