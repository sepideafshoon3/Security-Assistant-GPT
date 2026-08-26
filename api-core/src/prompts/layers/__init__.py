"""Layered prompting library for Mr Robot.

Supports:
- **single-layer** composition (classic system + user)
- **multi-layer** composition (ordered, prioritised, conditional stacks)

Powered by Jinja2 for template variables and condition expressions.
"""

from src.prompts.layers.engine import PromptEngine
from src.prompts.layers.errors import (
    LayerConditionError,
    LayerConfigError,
    LayerRegistryError,
    LayerRenderError,
    PromptLayerError,
)
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
from src.prompts.layers.registry import (
    ContentRegistry,
    build_default_registry,
    build_openai_registry,
    build_registry_for_provider,
    build_xai_registry,
)
from src.prompts.layers.renderer import PromptRenderer
from src.prompts.layers.secure_chat import (
    build_planner_prompts,
    build_secure_chat_composed,
    build_secure_chat_messages,
    get_default_engine,
    get_engine_for_provider,
)
from src.prompts.layers.stacks import (
    build_planner_stack,
    build_secure_chat_stack,
    stack_to_dict,
)

__all__ = [
    # Engine
    "PromptEngine",
    "PromptRenderer",
    "ContentRegistry",
    "build_default_registry",
    "build_openai_registry",
    "build_xai_registry",
    "build_registry_for_provider",
    "get_default_engine",
    "get_engine_for_provider",
    # Models
    "PromptMode",
    "PromptRole",
    "PromptLayerConfig",
    "PromptStackConfig",
    "ComposedPrompt",
    "SingleLayerRequest",
    "AppliedLayerInfo",
    "SkippedLayerInfo",
    # Errors
    "PromptLayerError",
    "LayerConfigError",
    "LayerRenderError",
    "LayerConditionError",
    "LayerRegistryError",
    # Stacks / integration helpers
    "build_secure_chat_stack",
    "build_planner_stack",
    "stack_to_dict",
    "build_secure_chat_composed",
    "build_secure_chat_messages",
    "build_planner_prompts",
]
