"""Default prompt stacks for Mr Robot chat and planner paths."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.prompts.layers.models import (
    PromptLayerConfig,
    PromptMode,
    PromptRole,
    PromptStackConfig,
)


def _sys(
    layer_id: str,
    *,
    order: int,
    content_ref: Optional[str] = None,
    content: Optional[str] = None,
    condition: Optional[str] = None,
    priority: int = 0,
    enabled: bool = True,
    variables: Optional[Dict[str, Any]] = None,
) -> PromptLayerConfig:
    kwargs: Dict[str, Any] = {
        "id": layer_id,
        "role": PromptRole.SYSTEM,
        "order": order,
        "priority": priority,
        "enabled": enabled,
        "condition": condition,
        "variables": variables or {},
    }
    if content_ref is not None:
        kwargs["content_ref"] = content_ref
    else:
        kwargs["content"] = content if content is not None else ""
    return PromptLayerConfig.model_validate(kwargs)


def build_secure_chat_stack(
    *,
    security_mode: bool = True,
    include_api_system: bool = False,
    include_dark_recon: bool = False,
    include_api_user: bool = False,
    include_grok: bool = False,  # NEW: flag to include Grok prompt
    mode: PromptMode = PromptMode.MULTI,
    merge_same_role: bool = False,
    provider: str = "openai",  # NEW: provider context
) -> PromptStackConfig:
    """Build the configurable secure_chat layer stack.

    This is the single source of truth for secure-chat system layers.
    Order and content preserve the former ``_build_secure_chat_messages_legacy``
    assembly (root/raw/style/policy/skills/developer/steps/… plus optional
    API and dark_recon context). Layers are enableable, reorderable, and
    conditional.

    Dynamic content (API system prompt, dark_recon JSON, API user msg)
    is supplied at compose-time via *variables* and optional inline
    layers toggled by the include_* flags.
    """
    layers: List[PromptLayerConfig] = []

    # --- Security persona stack (heavy) ---
    # order mirrors previous list construction for behavioural parity
    layers.extend(
        [

        ]
    )

    # NEW: Add Grok prompt layer for XAI provider
    if include_grok and provider == "xai":
        layers.append(

        )
    elif include_grok and provider == "openai":
        # Optionally add a different prompt for OpenAI
        layers.append(
            _sys(

            )
        )

    # Dynamic / optional layers
    if include_api_system:
        layers.append(
            _sys(

            )
        )

    if include_dark_recon:
        layers.append(
            _sys(
    
            )
        )

    # policy_controls last among system layers for security mode
    layers.append(
        _sys(

        )
    )

    if include_api_user:
        layers.append(
            PromptLayerConfig.model_validate(

            )
        )

    # When not in security mode the conditions above already drop persona
    # layers, leaving style + core_system + structure — the slim general stack.
    _ = security_mode  # documented for callers; conditions read it from context

    return PromptStackConfig(
        name="secure_chat_security" if security_mode else "secure_chat_general",
        mode=mode,
        layers=layers,
        merge_same_role=merge_same_role,
        separator="\n\n",
    )


def build_planner_stack(
    *,
    with_evidence: bool = False,
    mode: PromptMode = PromptMode.SINGLE,
    provider: str = "openai",  # NEW: provider context
    include_grok: bool = False,  # NEW: include Grok in planner
) -> PromptStackConfig:
    """Planner path: multi-layer sources merged into a single system prompt.

    Preserves the historical concatenation used by ``run_planning_agent``.
    """
    layers = [

    ]
    
    # NEW: Add Grok prompt to planner for XAI provider
    if include_grok and provider == "xai":
        layers.append(
            _sys(
                "grok",
                order=55,
                content_ref="grok",
                priority=55,  # Between open_ai_policy and evidence
            )
        )
    
    if with_evidence:
        layers.append(
            _sys(
                "planner_evidence",
                order=60,
                content_ref="planner_with_evidence",
                priority=50,
            )
        )
    else:
        layers.append(
            _sys(
                "json_only",
                order=60,
                content="\n You are a JSON-only assistant.",
                priority=50,
            )
        )

    return PromptStackConfig(
        name="planner_with_evidence" if with_evidence else "planner_draft",
        mode=mode,
        layers=layers,
        merge_same_role=True,
        separator="",
    )


def build_prompt_stack_for_provider(
    *,
    provider: str = "openai",
    security_mode: bool = True,
    include_api_system: bool = False,
    include_dark_recon: bool = False,
    include_api_user: bool = False,
    include_grok: bool = True,  # Default to True for XAI
    mode: PromptMode = PromptMode.MULTI,
    merge_same_role: bool = False,
    stack_type: str = "secure_chat",  # "secure_chat" or "planner"
    with_evidence: bool = False,
) -> PromptStackConfig:
    """Factory function to build appropriate stack based on provider.
    
    This is the recommended way to build stacks as it handles provider-specific
    configurations automatically.
    """
    # Auto-enable Grok for XAI provider
    if provider == "xai" and include_grok is None:
        include_grok = True
    
    if stack_type == "planner":
        return build_planner_stack(
            with_evidence=with_evidence,
            mode=mode,
            provider=provider,
            include_grok=include_grok,
        )
    else:  # secure_chat
        return build_secure_chat_stack(
            security_mode=security_mode,
            include_api_system=include_api_system,
            include_dark_recon=include_dark_recon,
            include_api_user=include_api_user,
            include_grok=include_grok,
            mode=mode,
            merge_same_role=merge_same_role,
            provider=provider,
        )


def build_secure_chat_stack_for_openai(
    *,
    security_mode: bool = True,
    include_api_system: bool = False,
    include_dark_recon: bool = False,
    include_api_user: bool = False,
    mode: PromptMode = PromptMode.MULTI,
    merge_same_role: bool = False,
) -> PromptStackConfig:
    """Convenience function for OpenAI provider."""
    return build_secure_chat_stack(
        security_mode=security_mode,
        include_api_system=include_api_system,
        include_dark_recon=include_dark_recon,
        include_api_user=include_api_user,
        include_grok=False,
        mode=mode,
        merge_same_role=merge_same_role,
        provider="openai",
    )


def build_secure_chat_stack_for_xai(
    *,
    security_mode: bool = True,
    include_api_system: bool = False,
    include_dark_recon: bool = False,
    include_api_user: bool = False,
    mode: PromptMode = PromptMode.MULTI,
    merge_same_role: bool = False,
) -> PromptStackConfig:
    """Convenience function for XAI provider with Grok prompt included."""
    return build_secure_chat_stack(
        security_mode=security_mode,
        include_api_system=include_api_system,
        include_dark_recon=include_dark_recon,
        include_api_user=include_api_user,
        include_grok=True,  # Always include Grok for XAI
        mode=mode,
        merge_same_role=merge_same_role,
        provider="xai",
    )


def stack_to_dict(stack: PromptStackConfig) -> Dict[str, Any]:
    """Serialize a stack for config dumps / debugging."""
    return stack.model_dump(mode="json")