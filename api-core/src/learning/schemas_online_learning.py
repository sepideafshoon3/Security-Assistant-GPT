from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class IncomingOnlineLearningEvent(BaseModel):
    ts: float = Field(..., description="Unix timestamp when event was created")
    event_type: str = Field(..., description="Type of event, e.g. chat_turn, pipeline_full_result")
    payload: Dict[str, Any] = Field(..., description="Arbitrary event payload")
    risk_score: Optional[float] = Field(None, description="Optional risk score")
    meta: Optional[Dict[str, Any]] = Field(None, description="Optional metadata (source, ip, etc.)")


class IncomingOnlineLearningResponse(BaseModel):
    success: bool
    message: str