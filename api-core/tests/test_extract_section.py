"""``OpenAILLMAdvisor._extract_section`` pulls a titled section out of model text.

Regression: the regex used ``rf"...#{1,6}..."``. Inside an f-string that is
the tuple ``(1, 6)``, which added two stray capture groups, so
``m.group(1)`` was never the section body and the function returned ""
for every input (the ``llm_thinking`` log event was always "missing").
"""

from __future__ import annotations

import pytest

from src.llm.openai_client import OpenAILLMAdvisor

extract = OpenAILLMAdvisor._extract_section


@pytest.mark.parametrize(
    "text",
    [
        "## Thinking\nstep one\nstep two\n\n## Answer\nfinal",
        "###### Thinking\nstep one\nstep two\n\n# Answer\nfinal",
        "**Thinking**\nstep one\nstep two\n\n**Answer**\nfinal",
        "Thinking:\nstep one\nstep two\n\n---\nfinal",
        "intro\n\nTHINKING\nstep one\nstep two",
    ],
)
def test_extracts_body_for_common_heading_styles(text):
    assert extract(text, "Thinking") == "step one\nstep two"


def test_stops_at_next_markdown_heading():
    text = "## Thinking\nbody\n### Details\nnot part of thinking"
    assert extract(text, "Thinking") == "body"


def test_title_is_matched_literally():
    text = "## Plan (v1.0)\nbody\n## Next\nx"
    assert extract(text, "Plan (v1.0)") == "body"
    assert extract(text, "Plan (v1x0)") == ""


@pytest.mark.parametrize("text", ["", None, "no such section here", "## Other\nx"])
def test_missing_section_or_empty_input_returns_empty_string(text):
    assert extract(text, "Thinking") == ""
