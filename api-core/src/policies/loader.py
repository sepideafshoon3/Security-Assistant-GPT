from __future__ import annotations

from pathlib import Path

from src.core.policy_engine import PolicyEngine


def load_policy_engine(config_dir: Path) -> PolicyEngine:
    """Build a PolicyEngine from ``<config_dir>/policies/*.yaml``.

    Fails loudly when the directory is missing: an empty engine would
    deny every action and treat every repo as out of scope, which hides
    a deployment mistake behind plausible-looking behaviour.
    """
    policy_dir = Path(config_dir) / "policies"
    if not policy_dir.is_dir():
        raise FileNotFoundError(f"Policy directory not found: {policy_dir}")
    return PolicyEngine(policy_dir)
