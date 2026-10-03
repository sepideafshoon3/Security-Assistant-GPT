#!/usr/bin/env bash
# Smoke-test DATABASE_URL: runs migrations, then a real write + read
# round-trip. Use this to confirm the app is actually talking to
# Postgres correctly, not just that the URL parses.
#
#   docker compose up -d
#   DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/security_assistant \
#     ./scripts/check_db.sh
#
# Defaults to the local SQLite file if DATABASE_URL isn't set, so it's
# also a quick sanity check in everyday dev.

set -euo pipefail
cd "$(dirname "$0")/.."

python - <<'PY'
from src.db.migrate import run_migrations
from src.db.session import DATABASE_URL, SessionLocal, engine
from sqlalchemy import text

print(f"DATABASE_URL = {DATABASE_URL}")

print("Running migrations (alembic upgrade head)...")
run_migrations()

print("Round-tripping a write + read...")

with SessionLocal() as db:
    db.execute(
        text("CREATE TABLE IF NOT EXISTS _db_check (note TEXT)")
    )
    db.execute(
        text("INSERT INTO _db_check (note) VALUES ('check_db.sh')")
    )
    db.commit()

    row = db.execute(
        text("SELECT note FROM _db_check LIMIT 1")
    ).fetchone()

    db.execute(text("DROP TABLE _db_check"))
    db.commit()

assert row and row[0] == "check_db.sh", f"unexpected row: {row}"

print(f"Engine dialect: {engine.dialect.name}")
print("OK — migrations ran and a write/read round-trip succeeded.")
PY
