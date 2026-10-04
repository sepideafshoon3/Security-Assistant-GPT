from pathlib import Path

from src.core.policy_engine import PolicyEngine


def test_action_allowed():
    policy_dir = Path("config/policies")
    engine = PolicyEngine(policy_dir)
    assert engine.is_action_allowed("run_semgrep") is True


def test_exploit_generate_needs_human_approval():
    engine = PolicyEngine(Path("config/policies"))
    assert engine.is_action_allowed("exploit_generate") is True
    assert engine.requires_human_approval("exploit_generate") is True
    assert engine.requires_human_approval("run_semgrep") is False


def test_unknown_action_denied():
    engine = PolicyEngine(Path("config/policies"))
    assert engine.is_action_allowed("rm_rf") is False


def test_repository_scope():
    engine = PolicyEngine(Path("config/policies"))
    assert engine.is_repository_in_scope("/tmp/lab/demo") is True
    assert engine.is_repository_in_scope("/etc") is False
