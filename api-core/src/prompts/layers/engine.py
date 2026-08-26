"""Public facade for single-layer and multi-layer prompting."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Union

from src.prompts.layers.composer import PromptComposer
from src.prompts.layers.models import (
    ComposedPrompt,
    PromptLayerConfig,
    PromptMode,
    PromptStackConfig,
    SingleLayerRequest,
)
from src.prompts.layers.registry import (
    ContentRegistry,
    build_default_registry,
    build_registry_for_provider,
)
from src.prompts.layers.renderer import PromptRenderer


class PromptEngine:
    """Clean entry point for the rest of Mr Robot.

    Examples
    --------
    Single-layer (classic system + user)::

        engine = PromptEngine()
        result = engine.compose_single(
            system="You are {{ persona }}.",
            user="Explain {{ topic }}.",
            variables={"persona": "Mr Robot", "topic": "XSS"},
        )
        call_llm(system_prompt=result.system, user_prompt=result.user)

    Multi-layer stack::

        result = engine.compose_layers(
            [
                {"id": "core", "order": 10, "content_ref": "system"},
                {
                    "id": "root",
                    "order": 0,
                    "content_ref": "root_mode",
                    "condition": "security_mode",
                },
            ],
            context={"security_mode": True},
            user_message="Help me with lab XSS.",
        )
        messages = result.as_chat_messages()
    """

    def __init__(
        self,
        *,
        registry: Optional[ContentRegistry] = None,
        renderer: Optional[PromptRenderer] = None,
        use_default_registry: bool = False,
    ) -> None:
        if registry is not None:
            reg = registry
        elif use_default_registry:
            reg = build_default_registry()
        else:
            reg = ContentRegistry()
        self.registry = reg
        self.renderer = renderer or PromptRenderer(strict_undefined=True)
        self.composer = PromptComposer(registry=self.registry, renderer=self.renderer)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------
    @classmethod
    def default(cls) -> "PromptEngine":
        """Engine pre-loaded with the OpenAI (default) prompt module registry."""
        return cls(use_default_registry=True)

    @classmethod
    def for_provider(cls, provider: str) -> "PromptEngine":
        """Engine pre-loaded with the registry for ``openai`` or ``xai``."""
        return cls(registry=build_registry_for_provider(provider))

    @classmethod
    def empty(cls) -> "PromptEngine":
        """Engine with an empty content registry (ideal for unit tests)."""
        return cls(use_default_registry=False)

    # ------------------------------------------------------------------
    # Composition API
    # ------------------------------------------------------------------
    def compose_single(
        self,
        request: Union[SingleLayerRequest, Mapping[str, Any], None] = None,
        *,
        system: str = "",
        user: str = "",
        variables: Optional[Mapping[str, Any]] = None,
        system_is_template: bool = True,
        user_is_template: bool = True,
    ) -> ComposedPrompt:
        """Compose a classic one system + one user prompt."""
        return self.composer.compose_single(
            request,
            system=system,
            user=user,
            variables=variables,
            system_is_template=system_is_template,
            user_is_template=user_is_template,
        )

    def compose_layers(
        self,
        layers: Sequence[Union[PromptLayerConfig, Mapping[str, Any]]],
        *,
        variables: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        user_message: Optional[str] = None,
        merge_same_role: bool = False,
        separator: str = "\n\n",
        mode: Union[PromptMode, str] = PromptMode.MULTI,
    ) -> ComposedPrompt:
        """Compose a multi-layer (or merged single) stack from layer configs."""
        if isinstance(mode, str):
            mode = PromptMode(mode)
        return self.composer.compose_layers(
            layers,
            variables=variables,
            context=context,
            user_message=user_message,
            merge_same_role=merge_same_role,
            separator=separator,
            mode=mode,
        )

    def compose_stack(
        self,
        stack: Union[PromptStackConfig, Mapping[str, Any]],
        *,
        variables: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        user_message: Optional[str] = None,
    ) -> ComposedPrompt:
        """Compose from a full stack configuration object."""
        return self.composer.compose_stack(
            stack,
            variables=variables,
            context=context,
            user_message=user_message,
        )

    def compose(
        self,
        *,
        mode: Union[PromptMode, str] = PromptMode.SINGLE,
        system: str = "",
        user: str = "",
        layers: Optional[Sequence[Union[PromptLayerConfig, Mapping[str, Any]]]] = None,
        stack: Optional[Union[PromptStackConfig, Mapping[str, Any]]] = None,
        variables: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        user_message: Optional[str] = None,
        merge_same_role: bool = False,
    ) -> ComposedPrompt:
        """Unified switch between single-layer and multi-layer modes.

        Priority:
        1. ``stack`` if provided
        2. ``layers`` if provided (forces multi unless mode=single)
        3. classic ``system`` + ``user`` single-layer
        """
        if isinstance(mode, str):
            mode = PromptMode(mode)

        if stack is not None:
            return self.compose_stack(
                stack,
                variables=variables,
                context=context,
                user_message=user_message if user_message is not None else (user or None),
            )

        if layers is not None:
            return self.compose_layers(
                layers,
                variables=variables,
                context=context,
                user_message=user_message if user_message is not None else (user or None),
                merge_same_role=merge_same_role or mode == PromptMode.SINGLE,
                mode=mode if mode == PromptMode.SINGLE else PromptMode.MULTI,
            )

        return self.compose_single(
            system=system,
            user=user,
            variables=variables,
        )

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------
    def register(self, key: str, content: str, *, overwrite: bool = False) -> None:
        self.registry.register(key, content, overwrite=overwrite)

    def register_many(self, mapping: Mapping[str, str], *, overwrite: bool = False) -> None:
        self.registry.register_many(mapping, overwrite=overwrite)
