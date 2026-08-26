"""Mr Robot prompt modules and layered prompting library.

Provider-specific prompt bodies live under:

- :mod:`src.prompts.openai` (e.g. ``src.prompts.openai.system.SYSTEM``)
- :mod:`src.prompts.xai` (e.g. ``src.prompts.xai.system.SYSTEM``)

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
