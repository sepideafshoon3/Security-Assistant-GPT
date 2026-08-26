from __future__ import annotations

from typing import Any, Dict, List, Optional

# api-core/src/api/schemas_learning.py
from typing import Any, Dict, Optional, List

from pydantic import BaseModel, Field



class OnlineLearningEventRequest(BaseModel):
    """
    Single event that the teacher API forwards to the online learning backend.
    """
    event_type: str = Field(
        ...,
        description="Logical type/name of the event, e.g. 'chat_turn', 'openai_style_chat_turn'.",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary JSON payload describing the event.",
    )
    risk_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional normalized risk score in [0, 1].",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional client metadata (IP, UA, tags, etc.).",
    )


class OnlineLearningEventResponse(BaseModel):
    """
    Response wrapper for a single event send.
    Mirrors what /online-learning/events returns in http.py.
    """
    success: bool = Field(..., description="True if the event was delivered successfully.")
    status_code: int = Field(..., description="HTTP-style status code for the delivery result.")
    message: str = Field(..., description="Human-readable description of the result.")


class OnlineLearningBulkEvent(BaseModel):
    """
    An event inside the bulk request.
    Same shape as OnlineLearningEventRequest but used inside a list.
    """
    event_type: str = Field(..., description="Logical event name.")
    payload: Dict[str, Any] = Field(default_factory=dict)
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None


class OnlineLearningBulkRequest(BaseModel):
    """
    Bulk send of multiple events to the online learning backend.
    """
    events: List[OnlineLearningBulkEvent] = Field(
        default_factory=list,
        description="List of events to send.",
    )


class OnlineLearningBulkResponse(BaseModel):
    """
    Response for /online-learning/bulk.
    """
    success: bool = Field(..., description="True if all events were sent successfully.")
    sent: int = Field(..., description="Number of events successfully delivered.")
    failed: int = Field(..., description="Number of events that failed.")
    message: str = Field(..., description="Summary message for the bulk operation.")