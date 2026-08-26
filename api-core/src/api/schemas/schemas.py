from pydantic import BaseModel
from typing import List,TypedDict, Dict, Optional, Literal



class CreateTaskRequest(BaseModel):
    description: str
    repository_path: str


class CreateTaskResponse(BaseModel):
    task_id: str


class ReportResponse(BaseModel):
    task_id: str
    summary: str


class ChatMessage(BaseModel):
    # Keep this simple to avoid Pydantic forward-ref issues
    role: str      # expected: "user" or "assistant" (or "system")
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


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
    in_scope: List[str]
    out_of_scope: List[str]
    clarifying_questions: List[ClarifyingQuestion]
    assumptions_if_no_answer: List[Assumption]
    missing_facts_to_research: List[ResearchQuery]
    initial_risks: List[str]


# ----------------------------------------------------------------------
# Evidence item (single search result)
# ----------------------------------------------------------------------
class EvidenceItem(TypedDict):
    id: str
    title: str
    snippet: str
    source: str  # domain or provider name
    url: str
    published_date: Optional[str]  # ISO if available
    retrieved_date: str            # ISO
    notes: Optional[str]


# ----------------------------------------------------------------------
# Final plan structures
# ----------------------------------------------------------------------
class DataEntity(TypedDict):
    name: str
    description: str
    fields: List[Dict]  # {"name": "...", "type": "...", "required": bool, "notes": "..."}


class ApiEndpoint(TypedDict):
    method: str
    path: str
    purpose: str
    auth: Optional[str]
    request_example: Dict
    response_example: Dict
    errors: List[Dict]  # {"code": "...", "when": "...", "body": {...}}


class Milestone(TypedDict):
    id: str
    name: str
    goals: List[str]
    tasks: List[str]
    deliverables: List[str]
    dependencies: List[str]


class AcceptanceTest(TypedDict):
    id: str
    scenario: str
    steps: List[str]
    expected: List[str]


class FinalPlan(TypedDict):
    summary: str
    restated_goal: str
    scope: Dict[str, List[str]]          # {"in_scope": [...], "out_of_scope": [...]}
    architecture: Dict[str, any]          # components, data flow, stack, alternatives
    data_model: List[DataEntity]
    api: List[ApiEndpoint]
    ui_screens: List[Dict]               # optional UI mock‑ups
    security: Dict[str, any]
    observability: Dict[str, any]         # logs/metrics/traces
    performance: Dict[str, any]
    milestones: List[Milestone]
    risks: List[Dict]                     # {"risk":"...", "mitigation":"..."}
    acceptance_tests: List[AcceptanceTest]
    open_questions: List[ClarifyingQuestion]
    assumptions: List[Assumption]
    evidence: List[EvidenceItem]          # full list of research items used