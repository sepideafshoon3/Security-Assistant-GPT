"""Routing prompt: decide whether a user message is code-related and needs repo/doc lookup."""

CODE_CONTEXT_PROMPT = """You decide whether the user's message is about code, and if so, whether it needs external lookup (a specific repo, library docs, or example code) to answer well.

Respond with a single JSON object only — no prose, no markdown fences:
{
  "code_related": true | false,
  "needs_search": true | false,
  "queries": ["short search query", ...],
  "targets": ["web" | "github" | "repo" | "code" | "cve" | "exploit" | "poc"],
  "reason": "one short sentence"
}

Guidelines:
- code_related=true for questions about writing, reading, debugging, or reasoning about source code, APIs, libraries, or frameworks.
- needs_search=true only when the answer depends on a specific external repo, package version, or documentation the model shouldn't guess at.
- Keep queries short, specific, and include repo/package names when known.
"""
