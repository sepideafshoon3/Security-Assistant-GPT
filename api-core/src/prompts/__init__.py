"""Mr Robot prompt modules and layered prompting library.

Prompt bodies live in :mod:`src.prompts.openai` and are shared by every
provider (the xAI advisor reuses them); the layered content registries are
built in :mod:`src.prompts.layers.registry`.

Layer composition is handled by :mod:`src.prompts.layers`. Provider
selection is owned by :mod:`src.llm.router`.
"""

from src.prompts.layers import (
    ComposedPrompt,
    LayerConfigError,
    PromptEngine,
    PromptLayerConfig,
    PromptMode,
    PromptStackConfig,
    build_secure_chat_messages,
    get_default_engine,
    get_engine_for_provider,
)

__all__ = [
    "ComposedPrompt",
    "LayerConfigError",
    "PromptEngine",
    "PromptLayerConfig",
    "PromptMode",
    "PromptStackConfig",
    "build_secure_chat_messages",
    "get_default_engine",
    "get_engine_for_provider",
]
