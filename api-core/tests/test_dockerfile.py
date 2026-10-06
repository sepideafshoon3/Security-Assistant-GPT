"""The API image only contains what the Dockerfile COPYs.

The app also needs files that live *outside* ``src`` at runtime (policy and
app config, Alembic). Forgetting one doesn't fail any test or CI job -- the
container just crashes on boot -- so pin the list here.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"

# Paths (relative to api-core/) the running app reads from its working dir.
REQUIRED_AT_RUNTIME = ["pyproject.toml", "src", "config", "alembic.ini", "migrations"]


def _copied_sources() -> set[str]:
    sources = set()
    for line in DOCKERFILE.read_text().splitlines():
        match = re.match(r"\s*COPY\s+(?!--)(.+)", line)
        if match:
            *srcs, _dest = match.group(1).split()
            sources.update(src.rstrip("/") for src in srcs)
    return sources


def test_dockerfile_copies_runtime_files():
    missing = [p for p in REQUIRED_AT_RUNTIME if p not in _copied_sources()]
    assert not missing, f"Dockerfile does not COPY: {missing}"


def test_required_files_exist_in_repo():
    base = DOCKERFILE.parent
    assert [p for p in REQUIRED_AT_RUNTIME if not (base / p).exists()] == []
