"""``load_llm_config`` merges app.yaml with environment overrides."""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

from src.llm.config import LLMConfig, load_llm_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("OPENAI_DEFAULT_CHAT_MODEL", "LLM_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)


def _write(tmp_path, body: str):
    (tmp_path / "app.yaml").write_text(body)
    return tmp_path


def test_reads_values_from_yaml_and_strips_model(tmp_path):
    cfg = load_llm_config(
        _write(
            tmp_path,
            "llm:\n  enabled: true\n  model: ' m-yaml '\n  temperature: 0.7\n"
            "  provider: xai\n  assistant_id: ' '\n",
        )
    )
    assert cfg.enabled is True
    assert cfg.model == "m-yaml"
    assert cfg.temperature == 0.7
    assert cfg.provider == "xai"
    assert cfg.assistant_id is None  # blank id collapses to None


def test_env_model_and_provider_override_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "m-env")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    cfg = load_llm_config(_write(tmp_path, "llm:\n  model: m-yaml\n  provider: xai\n"))
    assert (cfg.model, cfg.provider) == ("m-env", "openai")


def test_openai_default_chat_model_beats_llm_model(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "second")
    monkeypatch.setenv("OPENAI_DEFAULT_CHAT_MODEL", "first")
    assert load_llm_config(_write(tmp_path, "llm: {}\n")).model == "first"


def test_defaults_when_llm_section_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "m")
    cfg = load_llm_config(_write(tmp_path, "{}\n"))
    assert cfg.enabled is False
    assert cfg.max_tokens == 4096
    assert cfg.temperature == 0.2
    assert cfg.enable_planner is True
    assert cfg.enable_web_search is False
    assert cfg.web_search_external_access is True
    assert cfg.provider is None


@pytest.mark.parametrize(("raw", "expected"), [(999999, 65536), (0, 1), (-5, 1)])
def test_max_tokens_is_clamped_with_a_warning(
    tmp_path, monkeypatch, caplog, raw, expected
):
    monkeypatch.setenv("LLM_MODEL", "m")
    with caplog.at_level(logging.WARNING, logger="src.llm.config"):
        cfg = load_llm_config(_write(tmp_path, f"llm:\n  max_tokens: {raw}\n"))
    assert cfg.max_tokens == expected
    assert "clamping" in caplog.text


def test_in_range_max_tokens_is_untouched_and_silent(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("LLM_MODEL", "m")
    with caplog.at_level(logging.WARNING, logger="src.llm.config"):
        cfg = load_llm_config(_write(tmp_path, "llm:\n  max_tokens: 2048\n"))
    assert cfg.max_tokens == 2048
    assert "clamping" not in caplog.text


def test_missing_app_yaml_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_llm_config(tmp_path)


def test_real_app_yaml_loads():
    cfg = load_llm_config(__import__("pathlib").Path("config"))
    assert isinstance(cfg, LLMConfig) and cfg.model


def test_config_module_stays_a_leaf():
    code = (
        "import sys, src.llm.config; "
        "sys.exit(1 if 'src.llm.openai_client' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, timeout=60
    )
    assert result.returncode == 0, "src.llm.config imports openai_client"
