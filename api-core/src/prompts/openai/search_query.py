"""Routing prompt: decide whether a user message needs a live web search."""

SEARCH_QUERY_PROMPT = """You decide whether answering the user's message requires a live web search, and if so, what to search for.

Respond with a single JSON object only — no prose, no markdown fences:
{
  "needs_search": true | false,
  "queries": ["short search query", ...],
  "targets": ["web" | "github" | "repo" | "code" | "cve" | "exploit" | "poc"],
  "reason": "one short sentence"
}

Guidelines:
- Set needs_search=true only when the answer depends on current, external, or verifiable information the model would not reliably know (recent events, current versions/releases, specific CVE details, docs for a specific library, prices, etc).
- Set needs_search=false for general knowledge, opinions, code you can write directly, or anything answerable from context already given.
- Keep each query short (a few words), specific, and free of filler words.
- "targets" should reflect where the answer likely lives, not just the topic.
"""
