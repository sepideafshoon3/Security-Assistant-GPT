README.md
# Security Assistant GPT (Lab-Only)

A defensive, lab-only security assistant that:
- Plans secure analysis tasks.
- Runs static and dependency analysis via sandboxed tools.
- Enforces strict policies (lab scope, no self-replication, no real-world exploitation).

## Features

- FastAPI HTTP API
- CLI for quick runs
- Policy engine for allowed actions and lab-scopes
- Tool runners for:
  - semgrep
  - bandit
  - osv-scanner
- Immutable audit logging

## Quick Start (Dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env


Run API:

uvicorn src.api.http:app --reload


Run CLI:

python -m src.cli.cli --help