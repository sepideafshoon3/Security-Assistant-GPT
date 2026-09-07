from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator


class Task(BaseModel):
    id: str
    description: str
    repository_path: str
    actions: List[str] = Field(default_factory=list)


class PlannedAction(BaseModel):
    action: str
    params: dict
    requires_human_approval: bool = False


class Plan(BaseModel):
    task_id: str
    actions: List[PlannedAction]


class ToolResult(BaseModel):
    action: str
    success: bool
    output_path: Optional[str] = None
    errors: Optional[str] = None


class Report(BaseModel):
    task_id: str
    results: List[ToolResult]
    summary: str


class HistoryMessage(BaseModel):
    role: str
    content: str
    created_at: Optional[datetime] = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _assume_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class ConversationSummary(BaseModel):
    conversation_id: str
    theme: str
    keywords: list[str]
    num_messages: int
    last_updated: Optional[datetime] | None = None
    last_messages: list[HistoryMessage] = []

    @field_validator("last_updated", mode="before")
    @classmethod
    def _assume_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v