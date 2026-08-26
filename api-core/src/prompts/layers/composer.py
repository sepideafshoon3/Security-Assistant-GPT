"""Compose single-layer and multi-layer prompts from validated configs."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from src.prompts.layers.errors import LayerConfigError, LayerRegistryError
from src.prompts.layers.models import (
    AppliedLayerInfo,
    ComposedPrompt,
    PromptLayerConfig,
    PromptMode,
    PromptRole,
    PromptStackConfig,
    SingleLayerRequest,
    SkippedLayerInfo,
)
from src.prompts.layers.registry import ContentRegistry
from src.prompts.layers.renderer import PromptRenderer

LayerInput = Union[PromptLayerConfig, Mapping[str, Any]]
StackInput = Union[PromptStackConfig, Mapping[str, Any]]


class PromptComposer:
    """Validates, filters, renders, and stacks prompt layers."""

    def __init__(
        self,
        *,
        registry: Optional[ContentRegistry] = None,
        renderer: Optional[PromptRenderer] = None,
    ) -> None:
        self.registry = registry if registry is not None else ContentRegistry()
        self.renderer = renderer or PromptRenderer(strict_undefined=True)

    # ------------------------------------------------------------------
    # Public composition entry points
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
        """Classic single-layer path: one system + one user prompt.

        Fully backward-compatible with callers that previously built
        ``system_prompt`` / ``user_prompt`` strings by hand.
        """
        if request is not None:
            if isinstance(request, Mapping):
                req = SingleLayerRequest.model_validate(request)
            else:
                req = request
            system = req.system
            user = req.user
            variables = {**(req.variables or {}), **(variables or {})}
            system_is_template = req.system_is_template
            user_is_template = req.user_is_template

        vars_dict = dict(variables or {})

        if system_is_template and system:
            system_out = self.renderer.render(system, vars_dict, layer_id="system")
        else:
            system_out = system or ""

        if user_is_template and user:
            user_out = self.renderer.render(user, vars_dict, layer_id="user")
        else:
            user_out = user or ""

        messages: List[Dict[str, str]] = []
        applied: List[AppliedLayerInfo] = []
        if system_out:
            messages.append({"role": "system", "content": system_out})
            applied.append(
                AppliedLayerInfo(
                    id="system",
                    role=PromptRole.SYSTEM,
                    order=0,
                    priority=0,
                    char_count=len(system_out),
                )
            )
        if user_out:
            messages.append({"role": "user", "content": user_out})
            applied.append(
                AppliedLayerInfo(
                    id="user",
                    role=PromptRole.USER,
                    order=1,
                    priority=0,
                    char_count=len(user_out),
                )
            )

        return ComposedPrompt(
            mode=PromptMode.SINGLE,
            system=system_out,
            user=user_out,
            messages=messages,
            applied_layers=applied,
            skipped_layers=[],
            stack_name=None,
        )

    def compose_layers(
        self,
        layers: Sequence[LayerInput],
        *,
        variables: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        user_message: Optional[str] = None,
        merge_same_role: bool = False,
        separator: str = "\n\n",
        mode: PromptMode = PromptMode.MULTI,
        stack_name: Optional[str] = None,
    ) -> ComposedPrompt:
        """Compose an ordered, prioritised, conditional layer stack."""
        parsed = [self._parse_layer(item, index=i) for i, item in enumerate(layers)]
        self._assert_unique_ids(parsed, stack_name=stack_name)

        global_vars = dict(variables or {})
        ctx = dict(context or {})
        # Variables are also available inside condition expressions
        condition_ctx = {**global_vars, **ctx}

        ordered = sorted(
            parsed,
            key=lambda layer: (layer.order, -layer.priority, layer.id),
        )

        applied: List[AppliedLayerInfo] = []
        skipped: List[SkippedLayerInfo] = []
        rendered_parts: List[tuple[PromptLayerConfig, str]] = []

        for layer in ordered:
            if not layer.enabled:
                skipped.append(SkippedLayerInfo(id=layer.id, reason="disabled"))
                continue

            if layer.condition is not None:
                include = self.renderer.eval_condition(
                    layer.condition,
                    condition_ctx,
                    layer_id=layer.id,
                )
                if not include:
                    skipped.append(
                        SkippedLayerInfo(id=layer.id, reason="condition_false")
                    )
                    continue

            body = self._resolve_body(layer)
            layer_vars = {**global_vars, **(layer.variables or {})}
            self._check_required_variables(layer, layer_vars)

            text = self.renderer.render(body, layer_vars, layer_id=layer.id)
            # Drop empty renders (common when templates are fully conditional)
            if not (text or "").strip():
                skipped.append(SkippedLayerInfo(id=layer.id, reason="empty_render"))
                continue

            rendered_parts.append((layer, text))
            applied.append(
                AppliedLayerInfo(
                    id=layer.id,
                    role=layer.role,
                    order=layer.order,
                    priority=layer.priority,
                    char_count=len(text),
                )
            )

        if mode == PromptMode.SINGLE or merge_same_role:
            messages = self._merge_messages(rendered_parts, separator=separator)
        else:
            messages = [
                {"role": layer.role.value, "content": text}
                for layer, text in rendered_parts
            ]

        if user_message is not None:
            # Optional trailing user turn (not itself a stack layer)
            um = str(user_message)
            if global_vars:
                # Treat as template when variables are supplied
                um = self.renderer.render(um, global_vars, layer_id="user_message")
            if um.strip():
                messages.append({"role": "user", "content": um})

        system_text = separator.join(
            m["content"] for m in messages if m.get("role") == "system"
        )
        user_parts = [m["content"] for m in messages if m.get("role") == "user"]
        user_text = separator.join(user_parts)

        return ComposedPrompt(
            mode=mode,
            system=system_text,
            user=user_text,
            messages=messages,
            applied_layers=applied,
            skipped_layers=skipped,
            stack_name=stack_name,
        )

    def compose_stack(
        self,
        stack: StackInput,
        *,
        variables: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        user_message: Optional[str] = None,
    ) -> ComposedPrompt:
        """Compose from a named :class:`PromptStackConfig`."""
        cfg = self._parse_stack(stack)
        merge = cfg.merge_same_role or cfg.mode == PromptMode.SINGLE
        return self.compose_layers(
            cfg.layers,
            variables=variables,
            context=context,
            user_message=user_message,
            merge_same_role=merge,
            separator=cfg.separator,
            mode=cfg.mode,
            stack_name=cfg.name,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _parse_layer(self, item: LayerInput, *, index: int) -> PromptLayerConfig:
        try:
            if isinstance(item, PromptLayerConfig):
                return item
            return PromptLayerConfig.model_validate(item)
        except Exception as exc:
            layer_id = None
            if isinstance(item, Mapping):
                layer_id = item.get("id")
            raise LayerConfigError(
                f"invalid layer at index {index}: {exc}",
                layer_id=str(layer_id) if layer_id else None,
            ) from exc

    def _parse_stack(self, stack: StackInput) -> PromptStackConfig:
        try:
            if isinstance(stack, PromptStackConfig):
                return stack
            return PromptStackConfig.model_validate(stack)
        except Exception as exc:
            name = None
            if isinstance(stack, Mapping):
                name = stack.get("name")
            raise LayerConfigError(
                f"invalid stack config{f' ({name})' if name else ''}: {exc}"
            ) from exc

    def _assert_unique_ids(
        self,
        layers: Sequence[PromptLayerConfig],
        *,
        stack_name: Optional[str],
    ) -> None:
        seen: set[str] = set()
        for layer in layers:
            if layer.id in seen:
                where = f" in stack '{stack_name}'" if stack_name else ""
                raise LayerConfigError(
                    f"duplicate layer id{where}",
                    layer_id=layer.id,
                )
            seen.add(layer.id)

    def _resolve_body(self, layer: PromptLayerConfig) -> str:
        if layer.content_ref:
            try:
                return self.registry.get(layer.content_ref, layer_id=layer.id)
            except LayerRegistryError:
                raise
        body = layer.resolved_template()
        if body is None:
            raise LayerConfigError(
                "layer has no resolvable content",
                layer_id=layer.id,
            )
        return body

    def _check_required_variables(
        self,
        layer: PromptLayerConfig,
        variables: Mapping[str, Any],
    ) -> None:
        missing = [name for name in layer.required_variables if name not in variables]
        if missing:
            raise LayerConfigError(
                f"missing required variables: {missing}",
                layer_id=layer.id,
            )

    def _merge_messages(
        self,
        parts: Sequence[tuple[PromptLayerConfig, str]],
        *,
        separator: str,
    ) -> List[Dict[str, str]]:
        if not parts:
            return []

        messages: List[Dict[str, str]] = []
        current_role: Optional[PromptRole] = None
        bucket: List[str] = []

        def flush() -> None:
            nonlocal current_role, bucket
            if current_role is None or not bucket:
                current_role = None
                bucket = []
                return
            messages.append(
                {
                    "role": current_role.value,
                    "content": separator.join(bucket),
                }
            )
            current_role = None
            bucket = []

        for layer, text in parts:
            if current_role is None:
                current_role = layer.role
                bucket = [text]
            elif layer.role == current_role:
                bucket.append(text)
            else:
                flush()
                current_role = layer.role
                bucket = [text]
        flush()
        return messages
