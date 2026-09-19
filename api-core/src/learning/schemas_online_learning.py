from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IncomingOnlineLearningEvent(BaseModel):
    ts: float = Field(..., description="Unix timestamp when event was created")
    event_type: str = Field(
        ..., description="Type of event, e.g. chat_turn, pipeline_full_result"
    )
    payload: dict[str, Any] = Field(..., description="Arbitrary event payload")
    risk_score: float | None = Field(None, description="Optional risk score")
    meta: dict[str, Any] | None = Field(
        None, description="Optional metadata (source, ip, etc.)"
    )


class IncomingOnlineLearningResponse(BaseModel):
    success: bool
    message: str
