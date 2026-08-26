from pathlib import Path
from src.core.policy_engine import PolicyEngine


def test_action_allowed():
    policy_dir = Path("config/policies")
    engine = PolicyEngine(policy_dir)
    assert engine.is_action_allowed("run_semgrep") is True
