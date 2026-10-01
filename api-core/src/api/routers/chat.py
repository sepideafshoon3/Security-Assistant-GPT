from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from src.api.state import (
    chat_memory,
    executor,
    online_learning_dispatcher,
    resolve_llm_advisor,
)
from src.db.models import Conversation, GenerationJob, Message, User
from src.db.session import get_db
from src.learning.online_learning_events import ChatTurnEvent
from src.security.audit import audit_log
from src.security.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# ----------------------------------------------------------------------
# In-process "is this conversation currently streaming a reply" tracker.
#
# Intentionally NOT a DB column: this is only ever true while an SSE
# generator is actually running in this process, so it has no business
# surviving a restart — a column would need a migration (not set up yet)
# and would need manual reconciliation on every startup anyway. A plain
# in-memory counter (not a set) guards against double-counting if two
# requests ever race for the same conversation_id.
#
# Known limitation: this only works correctly with a single backend
# process. If/when this app runs with multiple uvicorn workers or
# multiple instances behind a load balancer, this needs to move to
# something shared (Redis, or a DB column after all) — a single
# in-memory counter can't see what another process is doing.
# ----------------------------------------------------------------------
_active_generations: Counter[str] = Counter()


def _mark_generating(conversation_id: str) -> None:
    _active_generations[conversation_id] += 1


def _unmark_generating(conversation_id: str) -> None:
    _active_generations[conversation_id] -= 1
    if _active_generations[conversation_id] <= 0:
        del _active_generations[conversation_id]


def is_generating(conversation_id: str) -> bool:
    return conversation_id in _active_generations


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


async def _chat_event_stream(
    conversation: Conversation,
    llm_messages: list[dict[str, str]],
    advisor: Any,
    is_first_turn: bool,
    db: Session,
) -> AsyncIterator[bytes]:
    """SSE body for POST /chat. Runs the (synchronous, blocking) LLM
    stream in a threadpool via iterate_in_threadpool so it doesn't block
    the event loop, forwards each text chunk to the client as it
    arrives, then persists the full reply and (on the first turn)
    triggers auto-titling once the stream ends.

    NOTE: this generator's actual behavior on client disconnect
    (does the except CancelledError branch really fire, does the
    partial reply really get saved) needs to be verified by testing
    against a live browser tab close / fetch abort — I can't run a
    live server here to confirm it. Task 3 (stop button) exercises
    this path directly.

    Also marks/unmarks this conversation in the in-process
    _active_generations counter for the whole lifetime of this turn
    (chunk streaming + persistence + title generation), so a page
    refresh mid-stream can poll /conversations/{id}/generation-status
    and show a "still generating" state instead of just losing the
    in-progress reply from view (see is_generating()/the status route
    below).
    """
    text_parts: list[str] = []

    yield _sse({"type": "start", "conversation_id": conversation.id})

    _mark_generating(conversation.id)
    try:
        try:
            sync_stream = advisor.secure_chat_stream(messages=llm_messages)
            async for piece in iterate_in_threadpool(sync_stream):
                if not piece:
                    continue
                text_parts.append(piece)
                yield _sse({"type": "chunk", "text": piece})
        except asyncio.CancelledError:
            _persist_stream_reply(db, conversation, "".join(text_parts).strip())
            raise
        except Exception as e:
            logger.exception(
                "[chat_stream] generation failed | conversation_id=%s", conversation.id
            )
            yield _sse({"type": "error", "message": str(e)})
            return

        full_text = "".join(text_parts).strip()
        _persist_stream_reply(db, conversation, full_text)

        if is_first_turn and conversation.title_is_generated:
            await _maybe_generate_title(
                conversation, advisor, llm_messages[-1]["content"], db
            )
    finally:
        _unmark_generating(conversation.id)

    yield _sse({"type": "done", "conversation_id": conversation.id})


# ============================================================
# Generation status — lets a page that just refreshed find out a
# conversation's reply is still being generated, so it can show a
# "still working" state and poll instead of showing nothing until the
# user manually resends. See _active_generations above for the (single
# process, in-memory) design and its limitation.
# ============================================================


@router.get("/conversations/{conversation_id}/generation-status")
async def get_generation_status(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
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

    return {"is_generating": is_generating(conversation_id)}


# ============================================================
# /chat: core chat endpoint (SSE streaming)
# ============================================================


@router.post("/chat")
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

    return StreamingResponse(
        _chat_event_stream(conversation, llm_messages, advisor, is_first_turn, db),
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
