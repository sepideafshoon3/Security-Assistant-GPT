from pathlib import Path

import pytest

from src.policies.loader import load_policy_engine


def test_loader_reads_real_config():
    engine = load_policy_engine(Path("config"))
    assert engine.is_action_allowed("run_bandit") is True


def test_loader_fails_loudly_without_policies(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_policy_engine(tmp_path)
