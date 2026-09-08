from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from time import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.state import (
    chat_memory,
    executor,
    online_learning_dispatcher,
    resolve_llm_advisor,
)
from src.db.models import Conversation, Message, User
from src.db.session import get_db
from src.learning.online_learning_events import ChatTurnEvent
from src.security.audit import audit_log
from src.security.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _maybe_generate_title(
    conversation: Conversation,
    advisor: Any,
    first_user_message: str,
    db: Session,
) -> None:
    if not conversation.title_is_generated:
        return
    try:
        title = advisor.secure_chat(messages=[
            {"role": "system", "content": "یک عنوان بسیار کوتاه (حداکثر ۵ کلمه) برای این گفتگو بده. فقط عنوان را برگردان."},
            {"role": "user", "content": first_user_message},
        ]).strip().strip('"')
        if title:
            conversation.title = title[:255]
            conversation.title_is_generated = False  # دیگه خودکار عوضش نکن
            db.commit()
    except Exception:
        logger.exception("[chat] title generation failed | id=%s", conversation.id)


# ============================================================
# /chat: core chat endpoint
# ============================================================

@router.post("/chat")
async def chat(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    data: Dict[str, Any] = await request.json()
    conversation_id: Optional[str] = data.get("conversation_id")
    raw_messages: List[Dict[str, Any]] = data.get("messages", [])
    # Optional per-request model → router picks openai vs xai client + prompts.
    advisor = resolve_llm_advisor(data.get("model") if isinstance(data, dict) else None)

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

    # Resolve or create the conversation — always scoped to current_user so
    # nobody can read/append to someone else's chat by guessing an id.
    conversation: Optional[Conversation] = None
    if conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
            .first()
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation is None:
        conversation = Conversation(user_id=current_user.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    history = [{"role": m.role, "content": m.content} for m in conversation.messages]
    llm_messages: List[Dict[str, str]] = history + [last_user_msg]

    try:
        reply_text: str = advisor.secure_chat(messages=llm_messages)
    except Exception as e:
        logger.exception("[chat] secure_chat failed | id=%s error=%r", conversation.id, e)
        raise HTTPException(status_code=500, detail=f"LLM chat failed: {e}")

    if len(history) == 0:
        _maybe_generate_title(conversation, advisor, last_user_msg["content"], db)

    db.add(Message(conversation_id=conversation.id, role="user", content=last_user_msg["content"]))
    db.add(Message(conversation_id=conversation.id, role="assistant", content=reply_text))
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()

    audit_log(
        "chat_request",
        {
            "conversation_id": conversation.id,
            "user_id": current_user.id,
            "num_history_messages": len(history),
            "uses_knowledge_file": False,
        },
    )

    # learning hook
    if online_learning_dispatcher is not None:
        try:
            from src.llm.model_config import get_chat_model

            evt = ChatTurnEvent(
                conversation_id=conversation.id,
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
            logger.exception("[chat] learning dispatch failed | id=%s", conversation.id)

    return {"conversation_id": conversation.id, "reply": reply_text}


# ============================================================
# OpenAI-compatible endpoint
# ============================================================

@router.post("/v1/chat/completions")
async def openai_compatible_chat(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
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
    advisor = resolve_llm_advisor(body.get("model"))

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