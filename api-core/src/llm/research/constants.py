"""Static word lists used by the research helpers and security-query detection."""

from __future__ import annotations

_RESEARCH_STOPWORDS = {
    "the",
    "and",
    "or",
    "but",
    "is",
    "are",
    "was",
    "were",
    "a",
    "an",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "by",
    "as",
    "at",
    "from",
    "that",
    "this",
    "it",
    "be",
    "can",
    "could",
    "should",
    "would",
    "about",
    "into",
    "over",
    "after",
    "before",
    "between",
    "latest",
    "newest",
    "recent",
    "current",
    "today",
}

_RESEARCH_SYNONYMS = {
    "latest": ["recent", "new", "current"],
    "newest": ["recent", "current"],
    "security": ["cybersecurity", "infosec"],
    "policy": ["regulation", "guidance"],
    "data": ["statistics", "figures", "metrics"],
    "report": ["publication", "study"],
    "research": ["analysis", "study"],
}

_RESEARCH_PACKAGE_REGISTRIES = [
    "pypi.org",
    "npmjs.com",
    "crates.io",
    "rubygems.org",
    "packagist.org",
    "nuget.org",
    "repo1.maven.org",
    "maven.org",
    "pkg.go.dev",
    "docs.rs",
]

_PLANNER_TARGETS = {
    "web",
    "github",
    "repo",
    "code",
    "cve",
    "exploit",
    "poc",
}

_REDTEAM_HINTS = (
    "cve",
    "exploit",
    "poc",
    "proof of concept",
    "proof-of-concept",
    "red team",
    "redteam",
    "pentest",
    "penetration test",
    "offensive",
    "payload",
    "metasploit",
    "nuclei",
    "0day",
    "0-day",
)

_GIT_REPO_HINTS = (
    "github",
    "gitlab",
    "bitbucket",
    "repo",
    "repository",
    "source code",
    "code",
)
