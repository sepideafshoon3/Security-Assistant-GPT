from typing import Literal, TypedDict

from pydantic import BaseModel


class CreateTaskRequest(BaseModel):
    description: str
    repository_path: str


class CreateTaskResponse(BaseModel):
    task_id: str


class ReportResponse(BaseModel):
    task_id: str
    summary: str


class ConversationRenameRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class ChatMessage(BaseModel):
    # Keep this simple to avoid Pydantic forward-ref issues
    role: str  # expected: "user" or "assistant" (or "system")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str


"""
TypedDict / Typed definitions for the planning agent.
All structures are JSON‑serialisable and match the description in the prompt.
"""


# ----------------------------------------------------------------------
# Draft stage structures
# ----------------------------------------------------------------------
class ClarifyingQuestion(TypedDict):
    id: str
    question: str
    why_it_matters: str
    blocking: bool  # True if cannot proceed without answer


class ResearchQuery(TypedDict):
    id: str
    query: str
    reason: str
    freshness: Literal["low", "medium", "high"]  # high = likely changed recently


class Assumption(TypedDict):
    id: str
    assumption: str
    impact: str
    can_change_later: bool


class PlanDraft(TypedDict):
    restated_goal: str
    in_scope: list[str]
    out_of_scope: list[str]
    clarifying_questions: list[ClarifyingQuestion]
    assumptions_if_no_answer: list[Assumption]
    missing_facts_to_research: list[ResearchQuery]
    initial_risks: list[str]


# ----------------------------------------------------------------------
# Evidence item (single search result)
# ----------------------------------------------------------------------
class EvidenceItem(TypedDict):
    id: str
    title: str
    snippet: str
    source: str  # domain or provider name
    url: str
    published_date: str | None  # ISO if available
    retrieved_date: str  # ISO
    notes: str | None


# ----------------------------------------------------------------------
# Final plan structures
# ----------------------------------------------------------------------
class DataEntity(TypedDict):
    name: str
    description: str
    fields: list[
        dict
    ]  # {"name": "...", "type": "...", "required": bool, "notes": "..."}


class ApiEndpoint(TypedDict):
    method: str
    path: str
    purpose: str
    auth: str | None
    request_example: dict
    response_example: dict
    errors: list[dict]  # {"code": "...", "when": "...", "body": {...}}


class Milestone(TypedDict):
    id: str
    name: str
    goals: list[str]
    tasks: list[str]
    deliverables: list[str]
    dependencies: list[str]


class AcceptanceTest(TypedDict):
    id: str
    scenario: str
    steps: list[str]
    expected: list[str]


class FinalPlan(TypedDict):
    summary: str
    restated_goal: str
    scope: dict[str, list[str]]  # {"in_scope": [...], "out_of_scope": [...]}
    architecture: dict[str, any]  # components, data flow, stack, alternatives
    data_model: list[DataEntity]
    api: list[ApiEndpoint]
    ui_screens: list[dict]  # optional UI mock‑ups
    security: dict[str, any]
    observability: dict[str, any]  # logs/metrics/traces
    performance: dict[str, any]
    milestones: list[Milestone]
    risks: list[dict]  # {"risk":"...", "mitigation":"..."}
    acceptance_tests: list[AcceptanceTest]
    open_questions: list[ClarifyingQuestion]
    assumptions: list[Assumption]
    evidence: list[EvidenceItem]  # full list of research items used
