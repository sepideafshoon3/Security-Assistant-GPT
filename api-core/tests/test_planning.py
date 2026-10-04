"""``run_planning_agent`` end to end with the LLM and search stubbed out.

The planner was moved verbatim out of ``openai_client.py``; these tests pin
its flow (draft -> auto-answer -> research_search -> evidence -> final plan)
and the wiring from ``/planner`` chat commands.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys

import pytest

from src.llm import planning


@pytest.fixture()
def stubbed(monkeypatch):
    calls = {"llm": [], "search": []}
    draft = {
        "questions": [{"id": "q1", "question": "Which DB?"}, {"id": "q2"}],
        "missing_facts": ["  fact A  ", "", "   ", 42],
        "assumptions": [],
    }
    final = {"summary": "the plan", "milestones": []}
    replies = iter([json.dumps(draft), json.dumps(final)])

    def fake_call_llm(system_prompt, user_prompt):
        calls["llm"].append((system_prompt, user_prompt))
        return next(replies)

    def fake_dispatch(name, args):
        calls["search"].append((name, args))
        return {
            "results": [
                {
                    "title": "T1",
                    "url": "https://a.example/1",
                    "snippet": "s1",
                    "source": "a.example",
                    "query": "fact A",
                },
                {"title": "T2", "url": "https://b.example/2"},
            ]
        }

    monkeypatch.setattr(planning, "call_llm", fake_call_llm)
    monkeypatch.setattr(
        planning,
        "setup_daily_llm_logger",
        lambda: logging.getLogger("test.planner.llm"),
    )
    # imported inside run_planning_agent, so patch the source module
    monkeypatch.setattr("src.tools.registry.dispatch_tool_call", fake_dispatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    return calls, draft, final


def test_auto_answer_skips_every_question():
    qs = [{"id": "a", "question": "x"}, {"id": "b", "question": "y"}]
    assert planning._auto_answer_questions(qs) == {"a": "skip", "b": "skip"}
    assert planning._auto_answer_questions([]) == {}


def test_planner_flow_builds_final_plan(stubbed):
    calls, draft, final = stubbed
    plan = planning.run_planning_agent("Build a todo app", top_k_per_query=5)

    assert plan["request"] == "Build a todo app"
    assert plan["draft"] == draft
    assert plan["final_plan"] == final
    assert plan["answers"] == {"q1": "skip", "q2": "skip"}

    # two LLM calls: draft, then synthesis with evidence
    assert len(calls["llm"]) == 2
    synthesis = calls["llm"][1][1]
    assert "Build a todo app" in synthesis and "https://a.example/1" in synthesis

    # one research_search with the cleaned, de-duplicated queries
    ((name, args),) = calls["search"]
    assert name == "research_search"
    assert set(args["queries"]) == {"fact A", "Build a todo app"}
    assert args["max_results_per_query"] == 10


def test_evidence_items_are_numbered_and_defaulted(stubbed):
    plan = planning.run_planning_agent("Build a todo app")
    ev = plan["evidence"]
    assert [e["id"] for e in ev] == ["1", "2"]
    assert ev[0]["title"] == "T1" and ev[0]["source"] == "a.example"
    assert ev[0]["notes"] == "Query: fact A"
    assert ev[1]["source"] == "web" and ev[1]["snippet"] == ""
    assert ev[0]["published_date"] is None and ev[0]["retrieved_date"]


def test_top_k_per_query_caps_queries(stubbed):
    calls, _, _ = stubbed
    planning.run_planning_agent("req", top_k_per_query=1)
    assert len(calls["search"][0][1]["queries"]) == 1


def test_planner_command_wiring(monkeypatch):
    from src.llm import openai_client as oc

    # the advisor must call the very function that lives in planning.py
    assert oc.run_planning_agent is planning.run_planning_agent

    seen = {}

    def fake_plan(request):
        seen["request"] = request
        return {"summary": "ok"}

    monkeypatch.setattr(oc, "run_planning_agent", fake_plan)
    advisor = oc.OpenAILLMAdvisor.__new__(oc.OpenAILLMAdvisor)

    out = advisor._handle_planner_command(
        [{"role": "user", "content": "/planner  build a thing "}]
    )
    assert seen["request"] == "build a thing"
    assert json.loads(out) == {"summary": "ok"}

    empty = advisor._handle_planner_command([{"role": "user", "content": "/planner"}])
    assert "No request supplied" in json.loads(empty)["error"]
    assert advisor._handle_planner_command([{"role": "user", "content": "hi"}]) is None

    def boom(_):
        raise RuntimeError("llm down")

    monkeypatch.setattr(oc, "run_planning_agent", boom)
    err = advisor._handle_planner_command([{"role": "user", "content": "/planner x"}])
    assert "Planner execution failed: llm down" in json.loads(err)["error"]


def test_planning_module_stays_a_leaf():
    code = (
        "import sys, src.llm.planning; "
        "sys.exit(1 if 'src.llm.openai_client' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, timeout=60
    )
    assert result.returncode == 0, "src.llm.planning imports openai_client"
