#!/usr/bin/env bash
set -euo pipefail

ruff src tests
mypy src
