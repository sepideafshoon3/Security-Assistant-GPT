# src/api/schemas_learning.py
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class OnlineLearningEventRequest(BaseModel):
    event_type: str = Field(
        ...,
        description="Logical type of the event, e.g. 'chat_turn', 'alert', 'feedback'",
    )
    payload: Dict[str, Any] = Field(
        ...,
        description="Arbitrary JSON payload for the learning backend",
    )
    risk_score: Optional[float] = Field(
        None,
        description="Optional risk score [0.0-1.0 or 0-100]",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional meta info (source, tags, user_id, conversation_id, etc.)",
    )


class OnlineLearningEventResponse(BaseModel):
    success: bool
    status_code: int
    message: str


class BulkOnlineLearningEventRequest(BaseModel):
    events: List[OnlineLearningEventRequest] = Field(
        ...,
        description="List of events to send in bulk",
    )


class BulkOnlineLearningEventResponse(BaseModel):
    success: bool
    total: int
    sent: int
    failed: int
    message: str