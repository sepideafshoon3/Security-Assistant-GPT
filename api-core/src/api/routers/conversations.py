from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

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