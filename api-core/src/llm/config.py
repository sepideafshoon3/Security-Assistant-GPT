"""LLM runtime configuration: the ``LLMConfig`` model and its loader.

Reads the ``llm:`` section of ``config/app.yaml``; environment variables
(``OPENAI_DEFAULT_CHAT_MODEL`` / ``LLM_MODEL``, ``LLM_PROVIDER``) take
precedence. Leaf module: it must not import ``src.llm.openai_client``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel

from src.llm.model_config import get_chat_model

logger = logging.getLogger(__name__)


class LLMConfig(BaseModel):
    enabled: bool
    model: str
    max_tokens: int = 65536
    temperature: float = 0.5
    top_p: float = 1.0
    assistant_id: str | None = None

    # <-- NEW FLAG: turn planner on/off globally
    enable_planner: bool = True  # set to False to disable

    # --- NEW: web search / internet access ---
    enable_web_search: bool = False
    web_search_external_access: bool = (
        True  # True = live internet, False = cached/offline
    )

    # Optional explicit provider override ("openai" | "xai"). When None, the
    # router auto-detects from the model name / LLM_PROVIDER env.
    provider: str | None = None


def load_llm_config(config_dir: Path) -> LLMConfig:
    import yaml

    app_yaml = config_dir / "app.yaml"
    with app_yaml.open() as f:
        data = yaml.safe_load(f) or {}

    llm_cfg = data.get("llm", {})

    # Env takes precedence over app.yaml so models can be switched without editing config.
    env_model = os.getenv("OPENAI_DEFAULT_CHAT_MODEL") or os.getenv("LLM_MODEL")
    model = (env_model or llm_cfg.get("model") or get_chat_model()).strip()

    # Explicit provider: LLM_PROVIDER env wins over app.yaml llm.provider.
    env_provider = (os.getenv("LLM_PROVIDER") or "").strip() or None
    yaml_provider = llm_cfg.get("provider")
    provider = env_provider or (str(yaml_provider).strip() if yaml_provider else None)

    # Hard-cap: values like 999999… break some providers and bloat logs.
    raw_max = int(llm_cfg.get("max_tokens", 4096))
    max_tokens = max(1, min(raw_max, 65536))
    if raw_max != max_tokens:
        logger.warning(
            "llm.max_tokens=%s is out of range; clamping to %s",
            raw_max,
            max_tokens,
        )

    return LLMConfig(
        enabled=bool(llm_cfg.get("enabled", False)),
        model=str(model),
        max_tokens=max_tokens,
        temperature=float(llm_cfg.get("temperature", 0.2)),
        top_p=float(llm_cfg.get("top_p", 1.0)),
        assistant_id=(
            str(llm_cfg.get("assistant_id")).strip() or None
            if llm_cfg.get("assistant_id")
            else None
        ),
        # <-- NEW: read the planner flag
        enable_planner=bool(llm_cfg.get("enable_planner", True)),
        # --- NEW ---
        enable_web_search=bool(llm_cfg.get("enable_web_search", False)),
        web_search_external_access=bool(
            llm_cfg.get("web_search_external_access", True)
        ),
        provider=provider,
    )
