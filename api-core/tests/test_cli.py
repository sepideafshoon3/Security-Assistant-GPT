"""Smoke tests for ``python -m src.cli.cli``.

Guards the failure that went unnoticed before: the CLI imported a module
that did not exist, so it crashed with ModuleNotFoundError on every run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cli import cli

API_CORE = Path(__file__).resolve().parents[1]


def test_cli_help_runs_as_documented():
    # Same invocation as the README, in a fresh process so import errors
    # surface exactly as a user would see them.
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.cli", "--help"],
        cwd=API_CORE,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "repository_path" in result.stdout


def test_out_of_scope_repo_exits_cleanly_without_llm(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(sys, "argv", ["cli", "/etc"])
    monkeypatch.setattr(cli, "audit_log", lambda name, _data: events.append(name))

    def _boom(*_a, **_k):
        raise AssertionError("Executor must not be built for out-of-scope paths")

    monkeypatch.setattr(cli, "Executor", _boom)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == "Repository out of lab scope"
    assert events == ["repo_out_of_scope"]


def test_in_scope_repo_runs_plan_and_prints_summary(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli", "/tmp/lab/demo"])

    class FakePlanner:
        def create_plan(self, task):
            return SimpleNamespace(task_id=task.id)

    class FakeExecutor:
        def __init__(self, **_kwargs):
            pass

        def execute_plan(self, _plan):
            return SimpleNamespace(summary="all good")

    monkeypatch.setattr(cli, "Planner", FakePlanner)
    monkeypatch.setattr(cli, "Executor", FakeExecutor)

    cli.main()

    out = capsys.readouterr().out
    assert "completed" in out
    assert "all good" in out
