from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.schemas.schemas import ConversationRenameRequest
from src.core.models import ConversationSummary
from src.db.models import Conversation, User
from src.db.session import get_db
from src.security.auth import get_current_user

router = APIRouter(tags=["conversations"])


@router.get("/conversations")
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )

    summaries: List[ConversationSummary] = []
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
            )
        )

    return {"conversations": [s.model_dump() for s in summaries]}


def _get_owned_conversation_or_404(
    conversation_id: str, current_user: User, db: Session
) -> Conversation:
    """Fetch a conversation, scoped to the caller. Returns a plain 404 for
    both "doesn't exist" and "belongs to someone else" — never reveal which,
    or the endpoint becomes a way to enumerate other users' conversation ids."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    conversation = _get_owned_conversation_or_404(conversation_id, current_user, db)
    db.delete(conversation)
    db.commit()


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    body: ConversationRenameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    conversation = _get_owned_conversation_or_404(conversation_id, current_user, db)

    new_title = body.title.strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="title must not be empty")

    conversation.title = new_title[:255]
    # Renaming is an explicit user choice — stop auto-titling from ever
    # overwriting it on a later turn.
    conversation.title_is_generated = False
    db.commit()
    db.refresh(conversation)

    return {
        "conversation_id": conversation.id,
        "theme": conversation.title,
        "last_updated": conversation.updated_at,
    }