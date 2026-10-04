"""Prompt-injection sanitizer for external (web / tool) content.

Leaf module: imported by ``openai_client`` and ``research.helpers``; it must
not import from either.
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS = re.compile(
    r"(?i)"
    r"(?:SYSTEM\s*(?:OVERRIDE|:))"
    r"|(?:ROOT\s*(?:ACTIVATED|MODE))"
    r"|(?:RAW\s*MODE)"
    r"|(?:ARCHITECT-\S+)"
    r"|(?:ignore\s+(?:all\s+)?previous\s+instructions)"
    r"|(?:ignore\s+(?:all\s+)?prior\s+instructions)"
    r"|(?:you\s+are\s+now\s+operating\s+(?:as|in|under))"
    r"|(?:all\s+safety\s+filters?\s+(?:are\s+)?disabled)"
    r"|(?:override\s+(?:all\s+)?(?:safety|policy|ethical))"
    r"|(?:jailbreak)"
    r"|(?:DAN\s+mode)"
    r"|(?:SIGMA-\S+)"
    r"|(?:OmegaCoder)"
    r"|(?:OFFENSIVE\s+PROFILE\s+LOADED)"
    r"|(?:MR\s+ROBOT\s+LOADED)"
    r"|(?:RootCore:)"
    r"|(?:you\s+must\s+obey\s+(?:every|all)\s+instructions?\s+without\s+question)"
    r"|(?:policy\s+(?:is\s+)?(?:disabled|overrid(?:den|e)|ignored))"
    r"|(?:no\s+(?:ethical|moral|safety)\s+(?:constraints?|restrictions?|guidelines?))"
    r"|(?:BEGIN\s+(?:JAILBREAK|EXPLOIT|PAYLOAD))"
)


def _sanitize_external_content(text: str, *, label: str = "content") -> str:
    """Neutralize prompopenai/gpt-oss-120bs in externalopenai/gpt-oss-120b   Replaces injection patterns with a redacted marker so the LLM
    sees that something was removed but cannot be influenced by it.
    """
    if not text:
        return text
    cleaned = _INJECTION_PATTERNS.sub(f"[REDACTED-{label}]", text)
    return cleaned
