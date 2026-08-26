from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

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


class ConversationSummary(BaseModel):
    conversation_id: str
    theme: str
    keywords: list[str]
    num_messages: int
    last_updated: Optional[datetime] | None = None
    last_messages: list[dict[str, str]] = []
