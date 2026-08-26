"""Helpers that wire the multi-layer prompt engine into secure_chat."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

from src.prompts.layers.engine import PromptEngine
from src.prompts.layers.models import ComposedPrompt, PromptMode
from src.prompts.layers.stacks import build_secure_chat_stack, build_planner_stack


def _env_prompt_mode() -> str:
    """Read prompting mode from environment.

    Values:
      - ``multi`` (default): discrete system messages per layer
      - ``single``: merge same-role layers into one system + user
    """
    raw = (os.getenv("MRROBOT_PROMPT_MODE") or os.getenv("PROMPT_MODE") or "multi").strip().lower()
    if raw in {"single", "multi"}:
        return raw
    return "multi"


def _env_include_grok() -> bool:
    """Read whether to include Grok prompt from environment.
    
    Values:
      - ``true``, ``1``, ``yes``: include Grok prompt
      - Default: ``false`` for OpenAI, but auto-enabled for XAI
    """
    raw = (os.getenv("MRROBOT_INCLUDE_GROK") or os.getenv("INCLUDE_GROK") or "").strip().lower()
    if raw in {"true", "1", "yes", "on"}:
        return True
    if raw in {"false", "0", "no", "off"}:
        return False
    # Auto-detect based on provider or default
    return False


def _normalize_provider(provider: Optional[str]) -> str:
    cleaned = (provider or "openai").strip().lower()
    if cleaned in {"xai", "x", "x-ai"}:
        return "xai"
    return "openai"


def _should_include_grok(provider: str, explicit: Optional[bool] = None) -> bool:
    """Determine if Grok prompt should be included.
    
    Priority:
    1. Explicit override if provided
    2. Environment variable
    3. Auto-enable for XAI provider
    """
    if explicit is not None:
        return explicit
    env_value = _env_include_grok()
    if env_value:
        return True
    # Auto-enable for XAI
    return provider == "xai"


@lru_cache(maxsize=4)
def get_engine_for_provider(provider: str = "openai") -> PromptEngine:
    """Process-wide engine for the given provider (``openai`` or ``xai``)."""
    return PromptEngine.for_provider(_normalize_provider(provider))


@lru_cache(maxsize=1)
def get_default_engine() -> PromptEngine:
    """Process-wide engine with the OpenAI (default) content registry."""
    return get_engine_for_provider("openai")


def build_secure_chat_composed(
    *,
    security_mode: bool,
    api_system_prompt: Optional[str] = None,
    api_user_message: Optional[str] = None,
    dark_recon_ctx: Optional[str] = None,
    mode: Optional[str] = None,
    engine: Optional[PromptEngine] = None,
    provider: Optional[str] = None,
    include_grok: Optional[bool] = None,  # NEW: explicit override
) -> ComposedPrompt:
    """Compose secure_chat system/context layers via the prompt engine.

    Does **not** append the caller's conversation ``messages`` — the caller
    should extend ``composed.messages`` with user/assistant history.

    When *engine* is omitted, *provider* selects the prompt package
    (``openai`` default, or ``xai``).
    
    When *include_grok* is omitted, it's auto-enabled for XAI provider.
    """
    resolved_provider = _normalize_provider(provider)
    resolved_mode = (mode or _env_prompt_mode()).lower()
    if resolved_mode not in {"single", "multi"}:
        resolved_mode = "multi"

    prompt_mode = PromptMode.SINGLE if resolved_mode == "single" else PromptMode.MULTI
    merge = resolved_mode == "single"

    has_api_system = bool(api_system_prompt and str(api_system_prompt).strip())
    has_api_user = bool(api_user_message and str(api_user_message).strip())
    has_dark_recon = bool(dark_recon_ctx and str(dark_recon_ctx).strip())
    
    # Determine if Grok should be included
    grok_enabled = _should_include_grok(resolved_provider, include_grok)

    stack = build_secure_chat_stack(
        security_mode=security_mode,
        include_api_system=has_api_system,
        include_dark_recon=has_dark_recon,
        include_api_user=has_api_user,
        include_grok=grok_enabled,  # NEW: pass Grok flag
        mode=prompt_mode,
        merge_same_role=merge,
        provider=resolved_provider,  # NEW: pass provider
    )

    context: Dict[str, Any] = {
        "security_mode": security_mode,
        "has_api_system": has_api_system,
        "has_api_user": has_api_user,
        "has_dark_recon": has_dark_recon,
        "has_grok": grok_enabled,  # NEW: track Grok in context
        "provider": resolved_provider,  # NEW: track provider in context
    }
    variables: Dict[str, Any] = {
        "api_system_prompt": api_system_prompt or "",
        "api_user_message": api_user_message or "",
        "dark_recon_ctx": dark_recon_ctx or "",
    }

    if engine is not None:
        eng = engine
    elif provider is not None:
        eng = get_engine_for_provider(provider)
    else:
        eng = get_default_engine()
    
    composed = eng.compose_stack(stack, variables=variables, context=context)
    
    # Log that Grok was included if enabled
    if grok_enabled:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[prompt] Grok prompt included for provider={resolved_provider}")
    
    return composed


def build_secure_chat_messages(
    *,
    conversation_messages: Sequence[Dict[str, str]],
    security_mode: bool = True,
    api_system_prompt: Optional[str] = None,
    api_user_message: Optional[str] = None,
    dark_recon_ctx: Optional[str] = None,
    mode: Optional[str] = None,
    engine: Optional[PromptEngine] = None,
    provider: Optional[str] = None,
    include_grok: Optional[bool] = None,  # NEW: explicit override
) -> List[Dict[str, str]]:
    """Full message list: composed layers + conversation history.

    This is the single source of truth for secure-chat message construction.
    All former legacy prompt content lives in the content registry and stack.
    """
    composed = build_secure_chat_composed(
        security_mode=security_mode,
        api_system_prompt=api_system_prompt,
        api_user_message=api_user_message,
        dark_recon_ctx=dark_recon_ctx,
        mode=mode,
        engine=engine,
        provider=provider,
        include_grok=include_grok,
    )
    out: List[Dict[str, str]] = list(composed.as_chat_messages())
    out.extend(list(conversation_messages or []))
    return out


def build_planner_prompts(
    *,
    user_request: str,
    with_evidence: bool = False,
    evidence_variables: Optional[Dict[str, Any]] = None,
    engine: Optional[PromptEngine] = None,
    provider: Optional[str] = None,
    include_grok: Optional[bool] = None,  # NEW: explicit override
) -> ComposedPrompt:
    """Single-layer-compatible planner system+user composition.

    Returns a :class:`ComposedPrompt` where ``.system`` and ``.user`` can be
    passed straight into ``call_llm`` (backward compatible).
    """
    resolved_provider = _normalize_provider(provider)
    grok_enabled = _should_include_grok(resolved_provider, include_grok)

    if engine is not None:
        eng = engine
    elif provider is not None:
        eng = get_engine_for_provider(provider)
    else:
        eng = get_default_engine()
    
    stack = build_planner_stack(
        with_evidence=with_evidence,
        mode=PromptMode.SINGLE,
        provider=resolved_provider,  # NEW: pass provider
        include_grok=grok_enabled,  # NEW: pass Grok flag
    )
    
    variables = dict(evidence_variables or {})
    variables.setdefault("user_request", user_request)

    composed = eng.compose_stack(
        stack,
        variables=variables,
        context={},
        user_message=user_request if not with_evidence else None,
    )

    if with_evidence:
        # evidence template may need user_request + research_results_json
        # Prefer explicit user body from variables if provided
        user_body = variables.get("user_prompt")
        if user_body is None:
            # Render planner evidence template as part of system already;
            # user is the synthesis payload when provided as user_request key
            user_body = variables.get("synthesis_prompt") or user_request
        composed = composed.model_copy(update={"user": str(user_body)})
        # Ensure messages end with user
        msgs = [m for m in composed.messages if m.get("role") != "user"]
        msgs.append({"role": "user", "content": str(user_body)})
        composed = composed.model_copy(update={"messages": msgs})
    
    # Log that Grok was included if enabled
    if grok_enabled:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[planner] Grok prompt included for provider={resolved_provider}")

    return composed


# NEW: Convenience functions for specific providers

def build_secure_chat_composed_for_openai(
    *,
    security_mode: bool = True,
    api_system_prompt: Optional[str] = None,
    api_user_message: Optional[str] = None,
    dark_recon_ctx: Optional[str] = None,
    mode: Optional[str] = None,
) -> ComposedPrompt:
    """Convenience function for OpenAI provider (no Grok)."""
    return build_secure_chat_composed(
        security_mode=security_mode,
        api_system_prompt=api_system_prompt,
        api_user_message=api_user_message,
        dark_recon_ctx=dark_recon_ctx,
        mode=mode,
        provider="openai",
        include_grok=False,
    )


def build_secure_chat_composed_for_xai(
    *,
    security_mode: bool = True,
    api_system_prompt: Optional[str] = None,
    api_user_message: Optional[str] = None,
    dark_recon_ctx: Optional[str] = None,
    mode: Optional[str] = None,
    include_grok: bool = True,  # Default True for XAI
) -> ComposedPrompt:
    """Convenience function for XAI provider (Grok enabled by default)."""
    return build_secure_chat_composed(
        security_mode=security_mode,
        api_system_prompt=api_system_prompt,
        api_user_message=api_user_message,
        dark_recon_ctx=dark_recon_ctx,
        mode=mode,
        provider="xai",
        include_grok=include_grok,
    )


def build_planner_prompts_for_openai(
    *,
    user_request: str,
    with_evidence: bool = False,
    evidence_variables: Optional[Dict[str, Any]] = None,
) -> ComposedPrompt:
    """Convenience function for OpenAI planner (no Grok)."""
    return build_planner_prompts(
        user_request=user_request,
        with_evidence=with_evidence,
        evidence_variables=evidence_variables,
        provider="openai",
        include_grok=False,
    )


def build_planner_prompts_for_xai(
    *,
    user_request: str,
    with_evidence: bool = False,
    evidence_variables: Optional[Dict[str, Any]] = None,
    include_grok: bool = True,  # Default True for XAI
) -> ComposedPrompt:
    """Convenience function for XAI planner (Grok enabled by default)."""
    return build_planner_prompts(
        user_request=user_request,
        with_evidence=with_evidence,
        evidence_variables=evidence_variables,
        provider="xai",
        include_grok=include_grok,
    )