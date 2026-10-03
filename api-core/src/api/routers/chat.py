from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.api.generation import (
    Generation,
    GenerationAlreadyRunningError,
    generation_manager,
)
from src.api.state import (
    chat_memory,
    executor,
    online_learning_dispatcher,
    resolve_llm_advisor,
)
from src.db.models import Conversation, GenerationJob, Message, User
from src.db.session import SessionLocal, get_db
from src.learning.online_learning_events import ChatTurnEvent
from src.prompts.task_prompts import build_title_gen_messages
from src.security.audit import audit_log
from src.security.auth import get_current_user
from src.security.rate_limit import CHAT_RATE_LIMIT, limiter

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
            messages=build_title_gen_messages(first_user_message),
        )
        title = raw_title.strip().strip('"')
        if title:
            conversation.title = title[:255]
            conversation.title_is_generated = False
            db.commit()
    except Exception:
        logger.exception("[chat] title generation failed | id=%s", conversation.id)


def _persist_stream_reply(
    db: Session, conversation: Conversation, content: str
) -> None:
    """Save the assistant's reply once a streamed response finishes or is
    interrupted. Called with whatever text was generated so far in both
    cases — a stopped generation keeps its partial answer, same as most
    chat apps do when you hit "stop"."""
    if not content:
        return
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=content,
        )
    )
    conversation.updated_at = datetime.now(UTC)
    db.commit()


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _persist_reply(conversation_id: str, content: str) -> None:
    """Persist the assistant reply from the background task.

    Opens its own session: the request-scoped one from ``get_db`` is closed
    by the time a refreshed/disconnected client's generation finishes.
    """
    if not content:
        return
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:  # deleted while it was generating
            return
        _persist_stream_reply(db, conversation, content)


async def _auto_title(
    conversation_id: str, advisor: Any, first_user_message: str
) -> None:
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is not None and conversation.title_is_generated:
            await _maybe_generate_title(conversation, advisor, first_user_message, db)


async def _sse_from_generation(
    gen: Generation, *, send_start: bool, send_snapshot: bool
) -> AsyncIterator[bytes]:
    """SSE body that *follows* a background generation.

    Closing this stream (page refresh, closed tab, network drop) does NOT
    stop the generation — only POST /conversations/{id}/stop does.
    """
    if send_start:
        yield _sse({"type": "start", "conversation_id": gen.conversation_id})

    start_index = 0
    if send_snapshot:
        # No await between these two lines, so text and index are consistent.
        start_index = len(gen.chunks)
        yield _sse({"type": "snapshot", "text": "".join(gen.chunks)})

    async for piece in generation_manager.subscribe(gen, start_index):
        yield _sse({"type": "chunk", "text": piece})

    if gen.error is not None:
        yield _sse({"type": "error", "message": gen.error})
        return
    yield _sse(
        {
            "type": "done",
            "conversation_id": gen.conversation_id,
            "stopped": gen.stopped,
        }
    )


def _get_owned_conversation(
    conversation_id: str, current_user: User, db: Session
) -> Conversation:
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
    return conversation


# ============================================================
# Generation control: status / re-attach after refresh / stop
# ============================================================


@router.get("/conversations/{conversation_id}/generation-status")
async def get_generation_status(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    _get_owned_conversation(conversation_id, current_user, db)
    return {"is_generating": generation_manager.is_active(conversation_id)}


@router.get("/conversations/{conversation_id}/stream", response_model=None)
async def reattach_generation_stream(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Re-attach to a running generation (e.g. after a page refresh).

    Sends one ``snapshot`` event with everything generated so far, then
    live ``chunk`` events until ``done``. 204 if nothing is running.
    """
    _get_owned_conversation(conversation_id, current_user, db)
    gen = generation_manager.get(conversation_id)
    if gen is None:
        return Response(status_code=204)
    return StreamingResponse(
        _sse_from_generation(gen, send_start=False, send_snapshot=True),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/conversations/{conversation_id}/stop")
async def stop_generation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Explicit Stop. The only thing that cancels a generation."""
    _get_owned_conversation(conversation_id, current_user, db)
    return {"stopping": generation_manager.stop(conversation_id)}


# ============================================================
# /chat: core chat endpoint (SSE streaming)
# ============================================================


@router.post("/chat")
@limiter.limit(CHAT_RATE_LIMIT)
async def chat(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
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

    if conversation is not None and generation_manager.is_active(conversation.id):
        raise HTTPException(
            status_code=409,
            detail="This conversation is still generating a reply.",
        )

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

    conversation_pk = conversation.id
    first_user_text = llm_messages[-1]["content"]
    try:
        gen = generation_manager.start(
            conversation_pk,
            advisor.secure_chat_stream(messages=llm_messages),
            persist=lambda text: _persist_reply(conversation_pk, text),
            after=(
                (lambda: _auto_title(conversation_pk, advisor, first_user_text))
                if is_first_turn
                else None
            ),
        )
    except GenerationAlreadyRunningError as e:
        raise HTTPException(
            status_code=409, detail="This conversation is still generating a reply."
        ) from e

    return StreamingResponse(
        _sse_from_generation(gen, send_start=True, send_snapshot=False),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ============================================================
# Legacy job-status routes — no longer written to by /chat.
# Left in place (harmless, unused for new chats) until the frontend's
# poll-based consumer is removed in Task 2; then GenerationJob and
# these two routes can be deleted together in one cleanup commit.
# ============================================================


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
