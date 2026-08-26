"""Central LLM model resolution from environment variables.

Priority for chat models:
  1. OPENAI_DEFAULT_CHAT_MODEL
  2. LLM_MODEL
  3. fallback default

Priority for embedding models:
  1. OPENAI_EMBEDDING_MODEL
  2. LLM_EMBEDDING_MODEL
  3. fallback default

Chat model values may be OpenAI ids (e.g. ``openai/gpt-oss-120b``,
``gpt-4.1``) or xAI / Grok ids (e.g. ``x-ai/grok-4.5``, ``grok-3``).
Provider selection is owned by :mod:`src.llm.router`.

Call sites should use these helpers instead of hardcoding model names so the
entire api-core stack can be reconfigured via .env without code changes.
"""

from __future__ import annotations

import os
from typing import Optional

# Fallback defaults used only when env vars are unset.
_FALLBACK_CHAT_MODEL = "openai/gpt-oss-120b"
_FALLBACK_EMBEDDING_MODEL = "text-embedding-3-small"


def get_chat_model() -> str:
    """Return the configured chat/completion model name from the environment."""
    return (
        os.getenv("OPENAI_DEFAULT_CHAT_MODEL")
        or os.getenv("LLM_MODEL")
        or _FALLBACK_CHAT_MODEL
    ).strip()


def get_embedding_model() -> str:
    """Return the configured embedding model name from the environment."""
    return (
        os.getenv("OPENAI_EMBEDDING_MODEL")
        or os.getenv("LLM_EMBEDDING_MODEL")
        or _FALLBACK_EMBEDDING_MODEL
    ).strip()


def get_provider(model: Optional[str] = None) -> str:
    """Return ``openai`` or ``xai`` for *model* (or the configured chat model).

    Delegates to :func:`src.llm.router.detect_provider` so heuristics stay in
    one place.
    """
    from src.llm.router import detect_provider

    return detect_provider(model or get_chat_model())
