"""Named prompt content registry for content_ref resolution."""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, MutableMapping, Optional

from src.prompts.layers.errors import LayerRegistryError
import logging

# Configure logger for this module
logger = logging.getLogger(__name__)

class ContentRegistry:
    """Maps stable string keys to prompt bodies (static strings or callables)."""

    def __init__(self, initial: Optional[Mapping[str, str]] = None) -> None:
        self._items: MutableMapping[str, str] = {}
        if initial:
            for key, value in initial.items():
                self.register(key, value)

    def register(self, key: str, content: str, *, overwrite: bool = False) -> None:
        cleaned = (key or "").strip()
        if not cleaned:
            raise LayerRegistryError("registry key must be a non-empty string")
        if not isinstance(content, str):
            raise LayerRegistryError(
                f"registry content for '{cleaned}' must be a string",
                ref=cleaned,
            )
        if cleaned in self._items and not overwrite:
            raise LayerRegistryError(
                f"key already registered: '{cleaned}'",
                ref=cleaned,
            )
        self._items[cleaned] = content

    def register_many(
        self,
        mapping: Mapping[str, str],
        *,
        overwrite: bool = False,
    ) -> None:
        for key, content in mapping.items():
            self.register(key, content, overwrite=overwrite)

    def get(self, key: str, *, layer_id: Optional[str] = None) -> str:
        cleaned = (key or "").strip()
        if not cleaned:
            raise LayerRegistryError(
                "content_ref must be a non-empty string",
                layer_id=layer_id,
                ref=key,
            )
        try:
            return self._items[cleaned]
        except KeyError as exc:
            known = ", ".join(sorted(self._items)) or "(empty)"
            raise LayerRegistryError(
                f"unknown content_ref; known keys: {known}",
                layer_id=layer_id,
                ref=cleaned,
            ) from exc

    def has(self, key: str) -> bool:
        return (key or "").strip() in self._items

    def keys(self) -> Iterable[str]:
        return sorted(self._items.keys())

    def as_dict(self) -> Dict[str, str]:
        return dict(self._items)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.has(key)

    def __len__(self) -> int:
        return len(self._items)


def _skills_blob(
    creative: str,
    psychology: str,
    kali: str,
    coding: str,
    ai: str,
) -> str:
    return (
        "Creative / generative security skills:\n"
        f"{creative}\n\n"
        "Psychology / communication:\n"
        f"{psychology}\n\n"
        "Kali Linux tools skills:\n"
        f"{kali}\n\n"
        "Coding skills:\n"
        f"{coding}\n"
        "AI:\n"
        f"{ai}"
    )


def build_openai_registry() -> ContentRegistry:
    """Register OpenAI prompt modules under stable content_ref keys."""
    return ContentRegistry(
        {
            "root": (
                "You are a security-focused coding assistant. You help the user "
                "review, analyze, and improve the security of code and systems "
                "they own or are explicitly authorized to test."
            ),
            "policy": (
                "Scope rules:\n"
                "- Only analyze code/targets the user owns or has explicit written authorization to test.\n"
                "- Do not produce attack plans, exploit chains, or payloads against third-party "
                "or unauthorized systems.\n"
                "- Static/dependency analysis (semgrep, bandit, osv-scanner) results should be explained "
                "in terms of the vulnerability and a concrete remediation, not an exploitation path.\n"
                "- If a request is about a target outside the user's declared scope, decline and ask "
                "for confirmation of ownership/authorization first."
            ),
            "style": (
                "Be direct and technical. Prefer concrete file/line references and fixes over general advice."
            ),
        }
    )


def build_xai_registry() -> ContentRegistry:
    # Same content — provider-specific overrides can be added later if needed.
    return build_openai_registry()


def build_default_registry() -> ContentRegistry:
    """Backward-compatible default: OpenAI prompt registry."""
    logger.info("Building default registry (OpenAI)")
    registry = build_openai_registry()
    logger.debug("Default registry built successfully")
    return registry


def build_registry_for_provider(provider: str) -> ContentRegistry:
    """Return the content registry for ``openai`` or ``xai``."""
    cleaned = (provider or "openai").strip().lower()
    logger.info(f"Building registry for provider: {provider!r} (normalized to: {cleaned})")
    
    if cleaned in {"xai", "x", "x-ai"}:
        logger.debug("Using XAI registry")
        registry = build_xai_registry()
        logger.info("XAI registry built successfully")
        return registry
    
    if cleaned in {"openai", "oai"}:
        logger.debug("Using OpenAI registry")
        registry = build_openai_registry()
        logger.info("OpenAI registry built successfully")
        return registry
    
    error_msg = f"unknown prompt provider: {provider!r} (expected 'openai' or 'xai')"
    logger.error(error_msg)
    raise ValueError(error_msg)