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
    include_dark_recon: bool = False,   # kept for signature compat, no-op below
    include_api_user: bool = False,
    include_grok: bool = False,
    mode: PromptMode = PromptMode.MULTI,
    merge_same_role: bool = False,
    provider: str = "openai",
) -> PromptStackConfig:
    layers: List[PromptLayerConfig] = [
        _sys("root", order=10, content_ref="root"),
        _sys("style", order=20, content_ref="style"),
        _sys("policy", order=30, content_ref="policy", priority=100),
    ]

    if include_api_system:
        layers.append(
            _sys(
                "api_system",
                order=40,
                content="{{ api_system_prompt }}",
                required_variables=["api_system_prompt"],
            )
        )

    # dark_recon injection intentionally removed — this stack no longer
    # feeds raw recon output into an "attack plan" persona.

    if include_api_user:
        layers.append(
            PromptLayerConfig.model_validate(
                {
                    "id": "api_user",
                    "role": PromptRole.USER,
                    "order": 90,
                    "content": "{{ api_user_message }}",
                    "required_variables": ["api_user_message"],
                }
            )
        )

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
    provider: str = "openai",
    include_grok: bool = False,  # currently unused, kept for signature compat
) -> PromptStackConfig:
    layers = [
        _sys("planner_root", order=10, content_ref="root"),
    ]

    if with_evidence:
        layers.append(
            _sys("planner_evidence", order=60, content="You must ground every step in the provided evidence.", priority=50)
        )
    else:
        layers.append(
            _sys("json_only", order=60, content="\nYou are a JSON-only assistant.", priority=50)
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