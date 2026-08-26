"""Central model/provider router for LLM clients and prompt packages.

Inspects the requested model name (and optional explicit provider / base URL), then:
- determines the provider (``openai`` vs ``xai``)
- selects the matching prompt engine / registry
- constructs the correct LLM advisor client

When the transport is **OpenRouter**, model ids are normalized to vendor
slugs required by OpenRouter::

    openai/<model>   e.g. openai/gpt-4.1
    x-ai/<model>     e.g. x-ai/grok-4.5   (also accepts input ``xai/...``)
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any, Literal, Optional, Union

from src.llm.model_config import get_chat_model

logger = logging.getLogger(__name__)

Provider = Literal["openai", "xai"]

# OpenRouter vendor prefixes (canonical slugs used in API requests).
OPENROUTER_OPENAI_PREFIX = "openai/"
OPENROUTER_XAI_PREFIX = "x-ai/"  # OpenRouter catalog slug for xAI
# Accepted aliases that we rewrite to the OpenRouter xAI slug.
_OPENROUTER_XAI_INPUT_PREFIXES = ("x-ai/", "xai/")

# OpenRouter / multi-provider style prefixes that map to xAI.
_XAI_PREFIXES = (
    "x-ai/",
    "xai/",
    "xai-",
)

# OpenRouter / multi-provider style prefixes that map to OpenAI.
_OPENAI_PREFIXES = (
    "openai/",
)

# Model name fragments that indicate xAI Grok models.
_XAI_NAME_RE = re.compile(
    r"(?i)(?:^|[/\-_.])grok(?:$|[/\-_.\d])|(?:^|[/\-_.])x-?ai(?:$|[/\-_.])"
)

# Known base-URL fragments → provider
_BASE_URL_XAI = (
    "api.x.ai",
    "x.ai/api",
    "x.ai/v1",
)
_BASE_URL_OPENAI = (
    "api.openai.com",
    "openai.com/v1",
)
_BASE_URL_OPENROUTER = (
    "openrouter.ai",
)


def is_openrouter_backend(base_url: Optional[str] = None) -> bool:
    """Return True when the effective API base URL is OpenRouter.

    Detection (any match wins):
      1. Explicit *base_url* argument
      2. ``LLM_GATEWAY=openrouter`` / ``OPENROUTER=1``
      3. ``OPENAI_BASE_URL`` / ``XAI_BASE_URL`` / ``LLM_BASE_URL`` contain
         ``openrouter.ai``
    """
    gateway = (os.getenv("LLM_GATEWAY") or os.getenv("LLM_BACKEND") or "").strip().lower()
    if gateway in {"openrouter", "or"}:
        return True
    flag = (os.getenv("OPENROUTER") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True

    candidates = [
        base_url,
        os.getenv("OPENAI_BASE_URL"),
        os.getenv("XAI_BASE_URL"),
        os.getenv("LLM_BASE_URL"),
    ]
    for raw in candidates:
        if raw and "openrouter.ai" in str(raw).strip().lower():
            return True
    return False


def _detect_provider_from_base_url(base_url: Optional[str] = None) -> Optional[Provider]:
    """Inspect base URL (argument + common env vars) and return provider if known.

    Returns None when the URL is missing or unrecognized.
    OpenRouter is treated as a transport, not a provider – callers should
    still decide openai vs xai from the model name.
    """
    candidates = [
        base_url,
        os.getenv("OPENAI_BASE_URL"),
        os.getenv("XAI_BASE_URL"),
        os.getenv("LLM_BASE_URL"),
    ]
    for raw in candidates:
        if not raw:
            continue
        lower = str(raw).strip().lower()
        if any(frag in lower for frag in _BASE_URL_OPENROUTER):
            # OpenRouter is a gateway; provider still comes from model / explicit
            return None
        if any(frag in lower for frag in _BASE_URL_XAI):
            return "xai"
        if any(frag in lower for frag in _BASE_URL_OPENAI):
            return "openai"
    return None


def detect_provider(
    model: Optional[str] = None,
    *,
    explicit: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Provider:
    """Return ``openai`` or ``xai`` for the given model / override / base URL.

    Precedence:
      1. *explicit* argument
      2. ``LLM_PROVIDER`` environment variable
      3. Base URL (argument or OPENAI_BASE_URL / XAI_BASE_URL / LLM_BASE_URL)
      4. Heuristics on the model name (``openai/…``, ``x-ai/…``, ``xai/…``, grok)
      5. Default ``openai``
    """
    if explicit is not None and str(explicit).strip():
        return _normalize_provider(str(explicit))

    env_provider = (os.getenv("LLM_PROVIDER") or "").strip()
    if env_provider:
        return _normalize_provider(env_provider)

    # NEW: try to infer from base API URL
    from_url = _detect_provider_from_base_url(base_url)
    if from_url is not None:
        return from_url

    name = (model or get_chat_model() or "").strip()
    if not name:
        return "openai"

    lower = name.lower()
    for prefix in _XAI_PREFIXES:
        if lower.startswith(prefix):
            return "xai"
    for prefix in _OPENAI_PREFIXES:
        if lower.startswith(prefix):
            return "openai"
    if "grok" in lower:
        return "xai"
    if _XAI_NAME_RE.search(name):
        return "xai"

    return "openai"


def _normalize_provider(value: str) -> Provider:
    cleaned = (value or "").strip().lower()
    if cleaned in {"xai", "x", "x-ai", "x_ai"}:
        return "xai"
    if cleaned in {"openai", "oai", "open-ai", "open_ai"}:
        return "openai"
    # Unknown explicit values fall back to model heuristics if possible
    logger.warning("unknown LLM provider %r; defaulting to openai", value)
    return "openai"


def _strip_vendor_prefix(model: str) -> str:
    """Remove known vendor prefixes (``openai/``, ``x-ai/``, ``xai/``)."""
    raw = (model or "").strip()
    lower = raw.lower()
    for prefix in ("openai/", "x-ai/", "xai/"):
        if lower.startswith(prefix):
            return raw[len(prefix) :]
    return raw


def normalize_model_for_provider(
    model: str,
    provider: Provider,
    *,
    openrouter: Optional[bool] = None,
    base_url: Optional[str] = None,
) -> str:
    """Normalize a model id for the active transport.

    **OpenRouter** (``openrouter=True`` or detected via base URL / env):
      - openai → ``openai/<id>``  (e.g. ``openai/gpt-4.1``)
      - xai    → ``x-ai/<id>``    (e.g. ``x-ai/grok-4.5``; accepts ``xai/…``)

    **Native provider APIs**:
      - xai    → bare id (strips ``x-ai/`` / ``xai/``)
      - openai → bare or passthrough (strips redundant ``openai/`` only when
        not using a multi-provider gateway)
    """
    raw = (model or "").strip()
    if not raw:
        return raw

    use_or = is_openrouter_backend(base_url) if openrouter is None else bool(openrouter)

    if use_or:
        bare = _strip_vendor_prefix(raw)
        if provider == "xai":
            # Canonical OpenRouter slug for xAI is ``x-ai/…`` (``xai/…`` accepted).
            return f"{OPENROUTER_XAI_PREFIX}{bare}"
        # openai (and any other → treat as openai vendor on OpenRouter)
        return f"{OPENROUTER_OPENAI_PREFIX}{bare}"

    # Native / non-OpenRouter backends
    if provider == "xai":
        return _strip_vendor_prefix(raw) if any(
            raw.lower().startswith(p) for p in ("x-ai/", "xai/", "openai/")
        ) else raw

    # Native OpenAI: strip openrouter-style openai/ prefix if present
    if raw.lower().startswith("openai/"):
        return raw[len("openai/") :]
    return raw


def get_prompt_registry(provider_or_model: Optional[str] = None) -> Any:
    """Return a :class:`ContentRegistry` for the provider (or model name)."""
    provider = _resolve_provider_arg(provider_or_model)
    from src.prompts.layers.registry import build_registry_for_provider

    return build_registry_for_provider(provider)


@lru_cache(maxsize=4)
def _cached_prompt_engine(provider: str) -> Any:
    from src.prompts.layers.engine import PromptEngine

    return PromptEngine.for_provider(provider)


def get_prompt_engine(provider_or_model: Optional[str] = None) -> Any:
    """Return a :class:`PromptEngine` for the provider (or model name)."""
    provider = _resolve_provider_arg(provider_or_model)
    return _cached_prompt_engine(provider)


def _resolve_provider_arg(provider_or_model: Optional[str]) -> Provider:
    if provider_or_model is None or not str(provider_or_model).strip():
        return detect_provider()
    value = str(provider_or_model).strip().lower()
    if value in {"openai", "oai", "open-ai", "open_ai", "xai", "x", "x-ai", "x_ai"}:
        return _normalize_provider(value)
    return detect_provider(provider_or_model)


def create_advisor(config: Any) -> Any:
    """Construct the correct LLM advisor for *config*.

    Uses ``config.provider`` when set; otherwise detects from ``config.model``
    and (if present) ``config.base_url`` / ``config.api_base``.
    Lazy-imports clients to keep light call sites free of heavy SDK imports.
    """
    model = getattr(config, "model", None) or get_chat_model()
    explicit = getattr(config, "provider", None)
    base_url = (
        getattr(config, "base_url", None)
        or getattr(config, "api_base", None)
        or getattr(config, "base", None)
    )
    provider = detect_provider(model, explicit=explicit, base_url=base_url)

    logger.info(
        "[router] create_advisor provider=%s model=%s base_url=%s",
        provider,
        model,
        base_url,
    )

    if provider == "xai":
        from src.llm.xai_client import XaiLLMAdvisor

        return XaiLLMAdvisor(config)

    from src.llm.openai_client import OpenAILLMAdvisor

    return OpenAILLMAdvisor(config)


# Process-level advisor cache (keyed by provider + model + enabled flag).
_advisor_cache: dict[tuple[str, str, bool], Any] = {}


def get_advisor(config: Any) -> Any:
    """Return a process-cached advisor for *config* (create on first use)."""
    model = str(getattr(config, "model", None) or get_chat_model() or "")
    explicit = getattr(config, "provider", None)
    base_url = (
        getattr(config, "base_url", None)
        or getattr(config, "api_base", None)
        or getattr(config, "base", None)
    )
    provider = detect_provider(model, explicit=explicit, base_url=base_url)
    enabled = bool(getattr(config, "enabled", False))
    key = (provider, model, enabled)
    if key not in _advisor_cache:
        _advisor_cache[key] = create_advisor(config)
    return _advisor_cache[key]


def clear_advisor_cache() -> None:
    """Drop cached advisors (for tests)."""
    _advisor_cache.clear()
    _cached_prompt_engine.cache_clear()


# Convenience module-level helpers matching a lightweight "router" object.
class ModelProviderRouter:
    """Object-oriented facade over the module-level router functions."""

    def detect_provider(
        self,
        model: Optional[str] = None,
        *,
        explicit: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Provider:
        return detect_provider(model, explicit=explicit, base_url=base_url)

    def is_openrouter_backend(self, base_url: Optional[str] = None) -> bool:
        return is_openrouter_backend(base_url)

    def normalize_model_for_provider(
        self,
        model: str,
        provider: Provider,
        *,
        openrouter: Optional[bool] = None,
        base_url: Optional[str] = None,
    ) -> str:
        return normalize_model_for_provider(
            model, provider, openrouter=openrouter, base_url=base_url
        )

    def get_prompt_engine(self, provider_or_model: Optional[str] = None) -> Any:
        return get_prompt_engine(provider_or_model)

    def get_prompt_registry(self, provider_or_model: Optional[str] = None) -> Any:
        return get_prompt_registry(provider_or_model)

    def create_advisor(self, config: Any) -> Any:
        return create_advisor(config)

    def get_advisor(self, config: Any) -> Any:
        return get_advisor(config)


_ROUTER: Optional[ModelProviderRouter] = None


def get_router() -> ModelProviderRouter:
    """Return the process-wide :class:`ModelProviderRouter` singleton."""
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelProviderRouter()
    return _ROUTER


AdvisorType = Union[Any, Any]  # OpenAILLMAdvisor | XaiLLMAdvisor (lazy)