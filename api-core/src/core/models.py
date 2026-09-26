from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class Task(BaseModel):
    id: str
    description: str
    repository_path: str
    actions: list[str] = Field(default_factory=list)


class PlannedAction(BaseModel):
    action: str
    params: dict
    requires_human_approval: bool = False


class Plan(BaseModel):
    task_id: str
    actions: list[PlannedAction]


class ToolResult(BaseModel):
    action: str
    success: bool
    output_path: str | None = None
    errors: str | None = None


class Report(BaseModel):
    task_id: str
    results: list[ToolResult]
    summary: str


class HistoryMessage(BaseModel):
    role: str
    content: str
    created_at: datetime | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _assume_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class ConversationSummary(BaseModel):
    conversation_id: str
    theme: str
    keywords: list[str]
    num_messages: int
    last_updated: datetime | None = None
    last_messages: list[HistoryMessage] = []
    pinned: bool = False

    @field_validator("last_updated", mode="before")
    @classmethod
    def _assume_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
