"""Task-specific prompts that sit alongside — but outside — the layered
secure_chat persona stack in ``prompts/layers/``.

These are single-purpose, structured-output prompts (e.g. "write a 5-word
title") rather than conversational persona layers, so they're kept as
plain versioned constants here instead of being folded into a
``PromptStackConfig``. They are still appended as extra messages when the
caller invokes ``advisor.secure_chat()``, so the standard root/style/policy
layers from ``prompts/layers/stacks.py`` are applied in front of them —
only the task-specific instruction below is new.

Extracted during the Week 4 prompt-engineering audit (see
``prompts/CHANGELOG.md``); previously this lived as an inline string in
``api/routers/chat.py``, unversioned and un-reviewable alongside the rest
of the prompt surface.
"""

from __future__ import annotations

TITLE_GEN_VERSION = "1.0.0"

TITLE_GEN_SYSTEM_PROMPT = (
    "Provide a very short title (maximum 5 words) for this conversation. "
    "Return only the title."
)


def build_title_gen_messages(first_user_message: str) -> list[dict[str, str]]:
    """Messages for the auto-title task.

    ``first_user_message`` is the first user turn of the conversation the
    title is being generated for.
    """
    return [
        {"role": "system", "content": TITLE_GEN_SYSTEM_PROMPT},
        {"role": "user", "content": first_user_message},
    ]
