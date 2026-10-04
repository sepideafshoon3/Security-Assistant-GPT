"""The ``/planner`` agent: draft a plan, gather evidence, return a ``FinalPlan``.

Extracted verbatim from ``openai_client.py``. Called by
``OpenAILLMAdvisor._handle_planner_command``. This module must not import
``src.llm.openai_client`` (the advisor imports it).

Note: ``src/agents/planner.py`` contains a different, currently unused
implementation of the same two functions.
"""

from __future__ import annotations

import datetime
import json
import logging
import os

from src.api.schemas.schemas import EvidenceItem, FinalPlan, PlanDraft
from src.llm.llm_logging import setup_daily_llm_logger
from src.llm.model_config import get_chat_model
from src.tools.utils import call_llm, parse_llm_json

logger = logging.getLogger(__name__)


def _auto_answer_questions(questions: list[dict[str, str]]) -> dict[str, str]:
    """
    Very simple auto‑answerer used for fully‑automated runs.
    Every question is answered with the placeholder “skip”.
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
    import datetime as _dt

    from src.tools.registry import dispatch_tool_call

    llm_log = setup_daily_llm_logger()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model_name = get_chat_model()

    # -----------------------------------------------------------------
    # 1. Draft plan
    # -----------------------------------------------------------------
    logger.info("=== STEP 1 - Draft plan ===")
    try:
        llm_log.info(
            json.dumps(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_request",
                    "layer": "planner_draft",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "user_request_len": len(user_request or ""),
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    # Single-layer path via PromptEngine (backward-compatible system+user strings)
    from src.prompts.layers import build_planner_prompts

    _planner_draft = build_planner_prompts(
        user_request=user_request, with_evidence=False
    )
    draft_raw = call_llm(
        system_prompt=_planner_draft.system,
        user_prompt=_planner_draft.user or user_request,
    )

    # Log draft result
    try:
        draft_text = (
            json.dumps(draft_raw, ensure_ascii=False, default=str)[:10_000]
            if draft_raw
            else ""
        )
        llm_log.info(
            json.dumps(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_response",
                    "layer": "planner_draft",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "text": draft_text,
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    parsed_llm_json = parse_llm_json(draft_raw)
    # -----------------------------------------------------------------
    # 2. Parse draft
    # -----------------------------------------------------------------
    try:
        draft_json = parsed_llm_json
    except Exception as e:
        logger.error(f"Failed to parse draft JSON: {e}")
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
    search_result = dispatch_tool_call(
        "research_search",
        {
            "queries": queries,
            "max_results_per_query": 10,
        },
    )

    raw_results = search_result.get("results", [])
    logger.info(
        "Planner research_search: %d queries -> %d results",
        len(queries),
        len(raw_results),
    )

    # Log research step
    try:
        llm_log.info(
            json.dumps(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_research",
                    "layer": "planner_research",
                    "queries_count": len(queries),
                    "results_count": len(raw_results),
                    "queries": [str(q)[:200] for q in queries],
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    # -----------------------------------------------------------------
    # 6. Build evidence items from tool results
    # -----------------------------------------------------------------
    evidence_items: list[EvidenceItem] = []
    now_iso = _dt.datetime.now(_dt.UTC).isoformat()

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
            evidence_dicts.append(
                e.dict() if callable(getattr(e, "dict", None)) else dict(e)
            )
        else:
            evidence_dicts.append(dict(e))

    synthesis_prompt = json.dumps(
        {
            "user_request": user_request,
            "answers": answers,
            "evidence": evidence_dicts,
        },
        ensure_ascii=False,
        indent=2,
    )

    try:
        llm_log.info(
            json.dumps(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_request",
                    "layer": "planner_synthesis",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "evidence_count": len(evidence_items),
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    from src.prompts.layers import build_planner_prompts

    _planner_final = build_planner_prompts(
        user_request=user_request,
        with_evidence=True,
        evidence_variables={
            "user_request": user_request,
            "research_results_json": json.dumps(
                evidence_items, ensure_ascii=False, default=str
            ),
            "synthesis_prompt": synthesis_prompt,
        },
    )
    final_raw = call_llm(
        system_prompt=_planner_final.system,
        user_prompt=_planner_final.user or synthesis_prompt,
    )

    # Log synthesis result
    try:
        final_text = (
            json.dumps(final_raw, ensure_ascii=False, default=str)[:10_000]
            if final_raw
            else ""
        )
        llm_log.info(
            json.dumps(
                {
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_response",
                    "layer": "planner_synthesis",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "text": final_text,
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    final_safe = parse_llm_json(final_raw)
    try:
        final_plan_dict = final_safe
    except Exception as e:
        logger.error(f"Failed to parse final plan JSON: {e}")
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
