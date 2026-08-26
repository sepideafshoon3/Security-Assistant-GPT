"""Errors raised by the layered prompting system."""

from __future__ import annotations


class PromptLayerError(Exception):
    """Base error for prompt layer configuration or composition failures."""


class LayerConfigError(PromptLayerError):
    """Raised when a layer or stack configuration is invalid."""

    def __init__(self, message: str, *, layer_id: str | None = None) -> None:
        self.layer_id = layer_id
        prefix = f"layer '{layer_id}': " if layer_id else ""
        super().__init__(f"{prefix}{message}")


class LayerRenderError(PromptLayerError):
    """Raised when a Jinja2 template fails to render."""

    def __init__(self, message: str, *, layer_id: str | None = None) -> None:
        self.layer_id = layer_id
        prefix = f"layer '{layer_id}': " if layer_id else ""
        super().__init__(f"{prefix}{message}")


class LayerConditionError(PromptLayerError):
    """Raised when a layer condition cannot be evaluated safely."""

    def __init__(self, message: str, *, layer_id: str | None = None) -> None:
        self.layer_id = layer_id
        prefix = f"layer '{layer_id}': " if layer_id else ""
        super().__init__(f"{prefix}{message}")


class LayerRegistryError(PromptLayerError):
    """Raised when a content_ref cannot be resolved from the registry."""

    def __init__(self, message: str, *, layer_id: str | None = None, ref: str | None = None) -> None:
        self.layer_id = layer_id
        self.ref = ref
        bits = []
        if layer_id:
            bits.append(f"layer '{layer_id}'")
        if ref:
            bits.append(f"content_ref '{ref}'")
        prefix = f"{', '.join(bits)}: " if bits else ""
        super().__init__(f"{prefix}{message}")
