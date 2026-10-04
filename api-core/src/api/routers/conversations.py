from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.api.schemas.schemas import ConversationRenameRequest
from src.core.models import ConversationSummary
from src.db.models import Conversation, GenerationJob, Project, User
from src.db.session import get_db
from src.security.auth import get_current_user
from src.security.rate_limit import WRITE_RATE_LIMIT, limiter

router = APIRouter(tags=["conversations"])


@router.get("/conversations")
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )

    summaries: list[ConversationSummary] = []
    for conv in conversations:
        history = [
            {"role": m.role, "content": m.content, "created_at": m.created_at}
            for m in conv.messages
        ]
        summaries.append(
            ConversationSummary(
                conversation_id=conv.id,
                theme=conv.title,
                keywords=[],
                num_messages=len(history),
                last_updated=conv.updated_at,
                last_messages=history[-5:],
                pinned=conv.pinned,
                project_id=conv.project_id,
            )
        )

    return {"conversations": [s.model_dump() for s in summaries]}


@router.get("/conversations/{conversation_id}/active-job")
async def get_active_job(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_owned_conversation_or_404(conversation_id, current_user, db)
    job = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.conversation_id == conversation_id,
            GenerationJob.status == "running",
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    return {"job_id": job.id if job else None}


def _get_owned_conversation_or_404(
    conversation_id: str, current_user: User, db: Session
) -> Conversation:
    """Fetch a conversation, scoped to the caller. Returns a plain 404 for
    both "doesn't exist" and "belongs to someone else" — never reveal which,
    or the endpoint becomes a way to enumerate other users' conversation ids."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id, Conversation.user_id == current_user.id
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit(WRITE_RATE_LIMIT)
async def delete_conversation(
    request: Request,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    conversation = _get_owned_conversation_or_404(conversation_id, current_user, db)
    db.delete(conversation)
    db.commit()


@router.patch("/conversations/{conversation_id}")
@limiter.limit(WRITE_RATE_LIMIT)
async def update_conversation(
    request: Request,
    conversation_id: str,
    body: ConversationRenameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conversation = _get_owned_conversation_or_404(conversation_id, current_user, db)

    if body.title is not None:
        new_title = body.title.strip()
        if not new_title:
            raise HTTPException(status_code=400, detail="title must not be empty")
        conversation.title = new_title[:255]
        conversation.title_is_generated = False

    if body.pinned is not None:
        conversation.pinned = body.pinned

    # Distinguish "field omitted" (leave assignment alone) from
    # "field sent as null" (remove from project) via model_fields_set —
    # body.project_id is None in both cases.
    if "project_id" in body.model_fields_set:
        if body.project_id is None:
            conversation.project_id = None
        else:
            project = (
                db.query(Project)
                .filter(
                    Project.id == body.project_id, Project.user_id == current_user.id
                )
                .first()
            )
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            conversation.project_id = project.id

    db.commit()
    db.refresh(conversation)

    return {
        "conversation_id": conversation.id,
        "theme": conversation.title,
        "last_updated": conversation.updated_at,
        "pinned": conversation.pinned,
        "project_id": conversation.project_id,
    }
