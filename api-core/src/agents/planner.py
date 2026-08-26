from __future__ import annotations

import json
import logging
import datetime as _dt
from typing import List, Dict, Any, Optional

from src.prompts.openai.planner import SYSTEM_PLANNER, USER_TO_PLAN_JSON, PLAN_WITH_EVIDENCE_JSON
from src.tools.utils import call_llm, parse_llm_json
from src.tools.registry import dispatch_tool_call
from src.api.schemas.schemas import PlanDraft, FinalPlan, EvidenceItem

log = logging.getLogger(__name__)

def _auto_answer_questions(questions: List[Dict[str, str]]) -> Dict[str, str]:
    """
    Very simple auto-answerer used for fully-automated runs.
    Every question is answered with the placeholder "skip".
    """
    return {q["id"]: "skip" for q in questions}

def run_planning_agent(user_request: str, *, top_k_per_query: int = 5) -> FinalPlan:
    """
    Executes the complete planning flow and returns a FinalPlan dict.

    Steps:
    1. Draft plan -> clarifying questions + missing-facts list.
    2. Auto-answer those questions (placeholder "skip").
    3. Build research queries from the request + answers.
    4. Use the local tool registry (research_search) for batch web search.
    5. Ask the LLM to synthesize the final plan with citations.
    """
    # -----------------------------------------------------------------
    # 1. Draft plan
    # -----------------------------------------------------------------
    log.info("=== STEP 1 - Draft plan ===")
    draft_raw = call_llm(
        system_prompt=SYSTEM_PLANNER,
        user_prompt=user_request,
    )
    # -----------------------------------------------------------------
    # 2. Parse draft (expecting JSON with questions, missing facts, etc.)
    # -----------------------------------------------------------------
    try:
        draft_json = parse_llm_json(draft_raw)
    except Exception as e:
        log.error(f"Failed to parse draft JSON: {e}")
        raise

    questions = draft_json.get("questions", [])
    missing_facts = draft_json.get("missing_facts", [])

    # -----------------------------------------------------------------
    # 3. Auto-answer questions
    # -----------------------------------------------------------------
    answers = _auto_answer_questions(questions)

    # -----------------------------------------------------------------
    # 4. Build research queries
    # -----------------------------------------------------------------
    queries = set()
    for fact in missing_facts:
        if isinstance(fact, str) and fact.strip():
            queries.add(fact.strip())
    if user_request.strip():
        queries.add(user_request.strip())
    queries = list(queries)[:top_k_per_query]

    # -----------------------------------------------------------------
    # 5. Use tool registry for batch search (research_search tool)
    # -----------------------------------------------------------------
    search_result = dispatch_tool_call("research_search", {
        "queries": queries,
        "max_results_per_query": 10,
    })

    raw_results = search_result.get("results", [])
    log.info(
        "Planner research_search: %d queries -> %d results",
        len(queries), len(raw_results),
    )

    # -----------------------------------------------------------------
    # 6. Build evidence items from tool results
    # -----------------------------------------------------------------
    evidence_items: List[EvidenceItem] = []
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()

    for idx, res in enumerate(raw_results, start=1):
        evidence_items.append(
            EvidenceItem(
                id=str(idx),
                title=res.get("title", ""),
                url=res.get("url", ""),
                snippet=res.get("snippet", ""),
                source=res.get("source", "web"),
                published_date=None,
                retrieved_date=now_iso,
                notes=f"Query: {res.get('query', '')}",
            )
        )

    # -----------------------------------------------------------------
    # 7. Ask LLM to synthesize final plan with citations
    # -----------------------------------------------------------------
    evidence_dicts = []
    for e in evidence_items:
        if hasattr(e, "dict"):
            evidence_dicts.append(e.dict() if callable(getattr(e, "dict", None)) else dict(e))
        else:
            evidence_dicts.append(dict(e))

    synthesis_prompt = json.dumps({
        "user_request": user_request,
        "answers": answers,
        "evidence": evidence_dicts,
    }, ensure_ascii=False, indent=2)

    final_raw = call_llm(
        system_prompt=PLAN_WITH_EVIDENCE_JSON,
        user_prompt=synthesis_prompt,
    )
    try:
        final_plan_dict = parse_llm_json(final_raw)
    except Exception as e:
        log.error(f"Failed to parse final plan JSON: {e}")
        raise

    # -----------------------------------------------------------------
    # 8. Construct FinalPlan object
    # -----------------------------------------------------------------
    final_plan = FinalPlan(
        request=user_request,
        draft=PlanDraft(**draft_json),
        answers=answers,
        evidence=evidence_items,
        final_plan=final_plan_dict,
    )
    return final_plan
