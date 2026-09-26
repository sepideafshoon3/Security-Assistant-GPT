from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from time import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.api.state import (
    chat_memory,
    executor,
    online_learning_dispatcher,
    resolve_llm_advisor,
)
from src.db.models import Conversation, GenerationJob, Message, User
from src.db.session import SessionLocal, get_db
from src.learning.online_learning_events import ChatTurnEvent
from src.security.audit import audit_log
from src.security.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


async def _maybe_generate_title(
    conversation: Conversation,
    advisor: Any,
    first_user_message: str,
    db: Session,
) -> None:
    if not conversation.title_is_generated:
        return
    try:
        raw_title = await run_in_threadpool(
            advisor.secure_chat,
            messages=[
                {
                    "role": "system",
                    "content": "Provide a very short title (maximum 5 words) for this conversation. Return only the title.",
                },
                {"role": "user", "content": first_user_message},
            ],
        )
        title = raw_title.strip().strip('"')
        if title:
            conversation.title = title[:255]
            conversation.title_is_generated = False
            db.commit()
    except Exception:
        logger.exception("[chat] title generation failed | id=%s", conversation.id)


# ============================================================
# Detached job runner — NOT awaited by the request handler
# ============================================================


async def _run_chat_job(
    job_id: str,
    conversation_id: str,
    llm_messages: list[dict[str, str]],
    advisor: Any,
    is_first_turn: bool,
) -> None:
    """Runs the LLM call and persists the result. Lives on the app's own
    event loop — cancelling the HTTP request that spawned it does nothing
    to this task."""
    db = SessionLocal()
    try:
        reply_text = await asyncio.get_running_loop().run_in_executor(
            None, lambda: advisor.secure_chat(messages=llm_messages)
        )

        conversation = (
            db.query(Conversation).filter(Conversation.id == conversation_id).first()
        )
        if conversation is not None:
            last_user_msg = llm_messages[-1]
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=reply_text,
                )
            )
            conversation.updated_at = datetime.now(UTC)

            if is_first_turn and conversation.title_is_generated:
                await _maybe_generate_title(
                    conversation, advisor, last_user_msg["content"], db
                )

        job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
        if job is not None:
            job.status = "done"
            job.result_text = reply_text

        db.commit()
    except Exception as e:
        logger.exception("[chat_job] failed | job_id=%s error=%r", job_id, e)
        try:
            db.rollback()
            job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
            if job is not None:
                job.status = "error"
                job.error_message = str(e)
                db.commit()
        except Exception:
            logger.exception(
                "[chat_job] FAILED TO MARK JOB AS ERRORED | job_id=%s", job_id
            )
    finally:
        db.close()


# ============================================================
# /chat: core chat endpoint
# ============================================================


@router.post("/chat")
async def chat(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    data: dict[str, Any] = await request.json()
    conversation_id: str | None = data.get("conversation_id")
    raw_messages: list[dict[str, Any]] = data.get("messages", [])
    advisor = resolve_llm_advisor(data.get("model") if isinstance(data, dict) else None)

    if (
        advisor is None
        or advisor.client is None
        or not getattr(advisor.config, "enabled", False)
    ):
        raise HTTPException(
            status_code=503, detail="LLM chat is disabled or unavailable."
        )

    new_messages: list[dict[str, str]] = []
    for m in raw_messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))
        if content:
            new_messages.append({"role": role, "content": content})

    if not new_messages:
        raise HTTPException(status_code=400, detail="No valid messages provided.")

    last_user_msg = next(
        (m for m in reversed(new_messages) if m["role"] == "user"), new_messages[-1]
    )

    conversation: Conversation | None = None
    if conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.user_id == current_user.id,
            )
            .first()
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    is_first_turn = conversation is None
    if conversation is None:
        conversation = Conversation(user_id=current_user.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    history = [{"role": m.role, "content": m.content} for m in conversation.messages]
    llm_messages = history + [last_user_msg]

    db.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=last_user_msg["content"],
        )
    )
    conversation.updated_at = datetime.now(UTC)

    job = GenerationJob(
        conversation_id=conversation.id, user_id=current_user.id, status="running"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # KEY LINE: create_task schedules this on the app's event loop as an
    # independent task. It is NOT a child of this request's coroutine, so
    # when Starlette cancels the request on client disconnect, this task
    # is untouched.
    asyncio.create_task(
        _run_chat_job(job.id, conversation.id, llm_messages, advisor, is_first_turn)
    )

    audit_log(
        "chat_request",
        {
            "conversation_id": conversation.id,
            "user_id": current_user.id,
            "num_history_messages": len(history),
            "uses_knowledge_file": False,
        },
    )

    return {"conversation_id": conversation.id, "job_id": job.id, "status": "running"}


@router.get("/chat/jobs/{job_id}")
async def get_chat_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = (
        db.query(GenerationJob)
        .filter(GenerationJob.id == job_id, GenerationJob.user_id == current_user.id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.id,
        "conversation_id": job.conversation_id,
        "status": job.status,
        "reply": job.result_text,
        "error": job.error_message,
    }


# ============================================================
# OpenAI-compatible endpoint
# ============================================================


@router.post("/v1/chat/completions")
async def openai_compatible_chat(
    request: Request,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = body.get("messages") or []
    from src.llm.model_config import get_chat_model

    model_name: str = (
        body.get("model")
        or getattr(getattr(executor.llm_advisor, "config", None), "model_name", None)
        or getattr(getattr(executor.llm_advisor, "config", None), "model", None)
        or get_chat_model()
    )
    # Router selects openai vs xai client (and that client selects prompt set).
    advisor = resolve_llm_advisor(body.get("model"))

    if (
        advisor is None
        or advisor.client is None
        or not getattr(advisor.config, "enabled", False)
    ):
        raise HTTPException(
            status_code=503, detail="LLM chat is disabled or unavailable."
        )

    conversation_id: str | None = body.get("conversation_id") or request.headers.get(
        "X-Conversation-ID"
    )

    new_messages: list[dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))
        if content:
            new_messages.append({"role": role, "content": content})

    if not new_messages:
        raise HTTPException(status_code=400, detail="No valid messages provided.")

    last_user_msg: dict[str, str] | None = None
    for m in reversed(new_messages):
        if m["role"] == "user":
            last_user_msg = m
            break
    if last_user_msg is None:
        last_user_msg = new_messages[-1]

    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        history: list[dict[str, str]] = []
    else:
        # Ownership check: a conversation_id that doesn't exist under THIS
        # user's own folder is either a typo or someone else's id — either
        # way, reject it rather than silently starting a fresh history
        # under an id we don't actually own.
        if not chat_memory.conversation_exists(current_user.id, conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        try:
            history = chat_memory.load_history(current_user.id, conversation_id) or []
        except Exception as e:
            logger.warning(
                "[openai_chat] load history failed | id=%s error=%r", conversation_id, e
            )
            history = []

    llm_messages: list[dict[str, str]] = history + [last_user_msg]

    try:
        reply_text: str = await run_in_threadpool(
            advisor.secure_chat, messages=llm_messages
        )
    except Exception as e:
        logger.exception(
            "[openai_chat] secure_chat failed | id=%s error=%r", conversation_id, e
        )
        raise HTTPException(status_code=500, detail=f"LLM chat failed: {e}") from e

    chat_memory.append_turn(
        current_user.id,
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
            logger.exception(
                "[openai_chat] learning dispatch failed | id=%s", conversation_id
            )

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
