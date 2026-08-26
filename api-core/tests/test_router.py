"""Tests for the model/provider router and xAI prompt package wiring."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from src.llm.openai_client import LLMConfig
from src.llm.router import (
    clear_advisor_cache,
    create_advisor,
    detect_provider,
    get_prompt_engine,
    get_prompt_registry,
    normalize_model_for_provider,
)
from src.prompts.layers import (
    build_openai_registry,
    build_secure_chat_messages,
    build_xai_registry,
    get_engine_for_provider,
)


# ---------------------------------------------------------------------------
# detect_provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("x-ai/grok-4.5", "xai"),
        ("xai/grok-beta", "xai"),
        ("xai-grok-3", "xai"),
        ("grok-3", "xai"),
        ("grok-4", "xai"),
        ("Grok-3-mini", "xai"),
        ("openai/gpt-oss-120b", "openai"),
        ("gpt-4.1", "openai"),
        ("gpt-4.1-mini", "openai"),
        ("o4-mini", "openai"),
        ("", "openai"),
    ],
)
def test_detect_provider_from_model(model, expected, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    # Pin fallback so empty model does not inherit the process .env chat model.
    monkeypatch.setenv("OPENAI_DEFAULT_CHAT_MODEL", "gpt-4.1-mini")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert detect_provider(model) == expected


def test_detect_provider_explicit_override_wins(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert detect_provider("gpt-4.1", explicit="xai") == "xai"
    assert detect_provider("grok-3", explicit="openai") == "openai"


def test_detect_provider_env_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "xai")
    assert detect_provider("gpt-4.1") == "xai"
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert detect_provider("grok-3") == "openai"


def test_normalize_model_native_strips_xai_prefix(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_GATEWAY", raising=False)
    monkeypatch.delenv("OPENROUTER", raising=False)
    assert normalize_model_for_provider("x-ai/grok-4.5", "xai", openrouter=False) == (
        "grok-4.5"
    )
    assert normalize_model_for_provider("xai/grok-3", "xai", openrouter=False) == "grok-3"
    assert normalize_model_for_provider("grok-3", "xai", openrouter=False) == "grok-3"
    assert normalize_model_for_provider(
        "openai/gpt-oss-120b", "openai", openrouter=False
    ) == "gpt-oss-120b"


def test_normalize_model_openrouter_vendor_prefixes():
    """OpenRouter requires openai/X and x-ai/X (xai/ accepted as input)."""
    assert (
        normalize_model_for_provider("grok-4.5", "xai", openrouter=True)
        == "x-ai/grok-4.5"
    )
    assert (
        normalize_model_for_provider("xai/grok-4.5", "xai", openrouter=True)
        == "x-ai/grok-4.5"
    )
    assert (
        normalize_model_for_provider("x-ai/grok-4.5", "xai", openrouter=True)
        == "x-ai/grok-4.5"
    )
    assert (
        normalize_model_for_provider("gpt-4.1", "openai", openrouter=True)
        == "openai/gpt-4.1"
    )
    assert (
        normalize_model_for_provider("openai/gpt-4.1", "openai", openrouter=True)
        == "openai/gpt-4.1"
    )
    assert (
        normalize_model_for_provider("gpt-oss-120b", "openai", openrouter=True)
        == "openai/gpt-oss-120b"
    )


def test_is_openrouter_from_base_url(monkeypatch):
    from src.llm.router import is_openrouter_backend

    monkeypatch.delenv("LLM_GATEWAY", raising=False)
    monkeypatch.delenv("OPENROUTER", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    assert is_openrouter_backend("https://openrouter.ai/api/v1") is True
    assert is_openrouter_backend("https://api.x.ai/v1") is False
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    assert is_openrouter_backend() is True


def test_openrouter_model_names_on_advisors(monkeypatch):
    """With OpenRouter base URL, both advisors emit vendor-prefixed model ids."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_GATEWAY", raising=False)

    clear_advisor_cache()
    xai_cfg = LLMConfig(enabled=False, model="grok-4.5")
    xai = create_advisor(xai_cfg)
    # disabled → no client, but _api_base_url may be unset; set for model format
    xai._api_base_url = "https://openrouter.ai/api/v1"
    xai._use_native_model_ids = False
    assert xai._get_model_name() == "x-ai/grok-4.5"

    oai_cfg = LLMConfig(enabled=False, model="gpt-4.1")
    oai = create_advisor(oai_cfg)
    oai._api_base_url = "https://openrouter.ai/api/v1"
    assert oai._get_model_name() == "openai/gpt-4.1"


# ---------------------------------------------------------------------------
# Registries / engines
# ---------------------------------------------------------------------------


def test_openai_registry_includes_open_ai_policy():
    reg = build_openai_registry()
    assert reg.has("open_ai_policy")
    assert reg.get("open_ai_policy").strip()  # non-empty
    assert reg.has("system")
    assert reg.has("policy_controls")


def test_xai_registry_omits_open_ai_policy_body():
    reg = build_xai_registry()
    assert reg.has("open_ai_policy")
    assert reg.get("open_ai_policy") == ""
    assert reg.has("system")
    assert reg.has("policy_controls")
    # Policy controls must not pull in OpenAiPolicy content
    assert "OPEN_AI_POLICY" not in reg.get("policy_controls")


def test_xai_prompt_rename_sanity():
    from src.prompts.xai.final_policy import FINAL_POLICY
    from src.prompts.xai.policy import POLICY

    # Renamed brand strings
    joined = FINAL_POLICY + POLICY
    assert "Xai" in joined or "xai" in joined.lower()
    assert "OpenAi" not in joined
    assert "OpenAI" not in joined


def test_no_xai_policy_module():
    xai_dir = Path(__file__).resolve().parents[1] / "src" / "prompts" / "xai"
    assert (xai_dir / "OpenAiPolicy.py").exists() is False
    assert (xai_dir / "XaiPolicy.py").exists() is False
    # Source OpenAiPolicy untouched
    openai_policy = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "prompts"
        / "openai"
        / "OpenAiPolicy.py"
    )
    assert openai_policy.is_file()


def test_secure_chat_with_xai_engine():
    engine = get_engine_for_provider("xai")
    msgs = build_secure_chat_messages(
        conversation_messages=[{"role": "user", "content": "hello lab"}],
        security_mode=True,
        mode="multi",
        engine=engine,
        provider="xai",
    )
    assert msgs
    assert any(m.get("role") == "system" for m in msgs)
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "hello lab"


def test_get_prompt_engine_via_router():
    eng_openai = get_prompt_engine("openai")
    eng_xai = get_prompt_engine("xai")
    eng_from_model = get_prompt_engine("x-ai/grok-4.5")
    assert eng_openai.registry.has("open_ai_policy")
    assert eng_openai.registry.get("open_ai_policy").strip()
    assert eng_xai.registry.get("open_ai_policy") == ""
    assert eng_from_model.registry.get("open_ai_policy") == ""


# ---------------------------------------------------------------------------
# create_advisor
# ---------------------------------------------------------------------------


def test_create_advisor_openai_disabled():
    clear_advisor_cache()
    cfg = LLMConfig(enabled=False, model="gpt-4.1-mini", provider="openai")
    advisor = create_advisor(cfg)
    from src.llm.openai_client import OpenAILLMAdvisor

    assert isinstance(advisor, OpenAILLMAdvisor)
    assert advisor.client is None


def test_create_advisor_xai_disabled():
    clear_advisor_cache()
    cfg = LLMConfig(enabled=False, model="x-ai/grok-4.5")
    advisor = create_advisor(cfg)
    from src.llm.xai_client import XaiLLMAdvisor

    assert isinstance(advisor, XaiLLMAdvisor)
    assert advisor.client is None


def test_create_advisor_xai_from_model_name():
    clear_advisor_cache()
    cfg = LLMConfig(enabled=False, model="grok-3")
    advisor = create_advisor(cfg)
    from src.llm.xai_client import XaiLLMAdvisor

    assert isinstance(advisor, XaiLLMAdvisor)


def test_create_advisor_openai_from_model_name():
    clear_advisor_cache()
    cfg = LLMConfig(enabled=False, model="openai/gpt-oss-120b")
    advisor = create_advisor(cfg)
    from src.llm.openai_client import OpenAILLMAdvisor
    from src.llm.xai_client import XaiLLMAdvisor

    assert isinstance(advisor, OpenAILLMAdvisor)
    assert not isinstance(advisor, XaiLLMAdvisor)


def test_xai_secure_chat_messages_use_xai_prompts():
    """XaiLLMAdvisor._build_secure_chat_messages pulls the xAI registry."""
    clear_advisor_cache()
    cfg = LLMConfig(enabled=False, model="grok-3")
    advisor = create_advisor(cfg)
    msgs = advisor._build_secure_chat_messages(
        messages=[{"role": "user", "content": "ping"}],
        api_system_prompt=None,
        api_user_message=None,
        dark_recon_ctx=None,
    )
    joined = "\n".join(str(m.get("content") or "") for m in msgs)
    # xAI-renamed strings should appear somewhere in the security stack
    assert "Xai" in joined or "xai" in joined.lower() or "Mr Robot" in joined
