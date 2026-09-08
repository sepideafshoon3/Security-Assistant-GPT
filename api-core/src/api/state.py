from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from src.core.executor import Executor
from src.core.paths import BASE_DIR
from src.core.planner import Planner
from src.learning.online_learning_client import OnlineLearningClient
from src.learning.online_learning_events import OnlineLearningEventDispatcher
from src.llm.openai_client import LLMConfig, load_llm_config
from src.llm.router import create_advisor, detect_provider, get_router
from src.memory.chat_memory import ChatMemory

logger = logging.getLogger(__name__)

# ============================================================
# Env & paths
# ============================================================

CONFIG_DIR: Path = BASE_DIR / "config"
REPORTS_DIR: Path = BASE_DIR / "data" / "reports"
CHAT_MEMORY_DIR: Path = BASE_DIR / "data" / "chat-memory"
DATA_DIR: Path = BASE_DIR / "data"

EVENTS_LOG_DIR: Path = BASE_DIR / "data" / "online-learning-events"
EVENTS_LOG_DIR.mkdir(parents=True, exist_ok=True)

DATASETS_DIR: Path = BASE_DIR / "data" / "online-learning-datasets"
DATASETS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# Core components (shared singletons — one instance per process)
# ============================================================

planner = Planner()
executor = Executor(
    reports_dir=REPORTS_DIR,
    config_dir=CONFIG_DIR,
)
chat_memory = ChatMemory(CHAT_MEMORY_DIR, max_messages=50)

# Central model/provider router (openai vs xai). Executor already builds its
# advisor through the same factory; helpers below re-resolve when a request
# overrides the model name.
_llm_router = get_router()


def resolve_llm_advisor(model_override: Optional[str] = None) -> Any:
    """Return the LLM advisor for the default config or a per-request model.

    Public call sites keep using ``executor.llm_advisor`` when no override is
    needed. When a request supplies a different model, the router selects the
    matching client (and that client selects the matching prompt set).
    """
    base = executor.llm_advisor
    override = (model_override or "").strip()
    if not override:
        return base

    base_model = ""
    base_provider = None
    if base is not None and getattr(base, "config", None) is not None:
        base_model = str(getattr(base.config, "model", "") or "")
        base_provider = getattr(base.config, "provider", None)

    if override == base_model:
        return base

    if detect_provider(override, explicit=base_provider) == detect_provider(
        base_model, explicit=base_provider
    ):
        # Same provider: reuse the existing client instance (model name on
        # config may still differ; callers pass model_name for logging only).
        return base

    try:
        cfg = load_llm_config(CONFIG_DIR)
        cfg = LLMConfig(
            enabled=cfg.enabled,
            model=override,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            assistant_id=cfg.assistant_id,
            enable_planner=cfg.enable_planner,
            enable_web_search=cfg.enable_web_search,
            web_search_external_access=cfg.web_search_external_access,
            provider=None,  # re-detect from model
        )
        return create_advisor(cfg)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[router] failed to resolve advisor for model=%s; falling back | error=%r",
            override,
            e,
        )
        return base


# ============================================================
# Online Learning Client wiring
# ============================================================

# .env:
# ONLINE_LEARNING_ENDPOINT=http://127.0.0.1:2121
# ONLINE_LEARNING_API_KEY=optional-token
online_learning_endpoint = os.getenv("ONLINE_LEARNING_ENDPOINT")
online_learning_api_key = os.getenv("ONLINE_LEARNING_API_KEY")

online_learning_client: Optional[OnlineLearningClient] = None
if online_learning_endpoint:
    online_learning_client = OnlineLearningClient(
        endpoint_url=online_learning_endpoint,
        api_key=online_learning_api_key,
        timeout=float(os.getenv("ONLINE_LEARNING_TIMEOUT", "5.0")),
        verify_ssl=os.getenv("ONLINE_LEARNING_VERIFY_SSL", "false").lower() in ("1", "true", "yes"),
    )
    logger.info(
        "[online-learning] client enabled | endpoint=%s",
        online_learning_endpoint,
    )
else:
    logger.warning("[online-learning] client disabled | ONLINE_LEARNING_ENDPOINT not set")

online_learning_dispatcher = OnlineLearningEventDispatcher(online_learning_client)