# src/llm/openai_client.py

import os
import logging
import datetime
import threading
import time
import tempfile
import subprocess
import shutil
import functools
import traceback
from html.parser import HTMLParser
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import json
import re
from openai import OpenAI
from pydantic import BaseModel

# ----------------------------------------------------------------------
# NEW IMPORTS FOR PLANNER INTEGRATION
# ----------------------------------------------------------------------
from src.tools.utils import call_llm, parse_llm_json
from src.search.tools_search import search_web, normalize_results
from src.api.schemas.schemas import PlanDraft, FinalPlan, EvidenceItem

# ----------------------------------------------------------------------
# Existing imports continued
# ----------------------------------------------------------------------
from src.security.audit import audit_log
from src.core.models import ToolResult
from src.search.exploitdb_client import ExploitMeta
from src.helpers.load_last_dark_recon import load_latest_dark_recon_summary
from src.search.local_web_search import web_search
from src.tools.registry import get_all_tool_schemas, dispatch_tool_call, get_tool_names

from src.prompts.openai.search_query import SEARCH_QUERY_PROMPT
from src.prompts.openai.code_context import CODE_CONTEXT_PROMPT
from src.prompts.layers import build_secure_chat_messages
from src.core.paths import BASE_DIR
from src.llm.model_config import get_chat_model

logger = logging.getLogger(__name__)


def normalize_openai_base_url(base_url: Optional[str]) -> Optional[str]:
    """Return a usable OpenAI API base URL.

    ``openai.com`` serves the web application and can respond with a
    Cloudflare challenge page. The SDK must use the API host instead.
    Accept the common website URL typo here so deployments fail less
    mysteriously when configuration is supplied outside ``.env``.
    """
    value = (base_url or "").strip()
    if not value:
        return None

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value

    if parsed.hostname == "openai.com":
        path = parsed.path.rstrip("/")
        if path in {"", "/api", "/api/v1"}:
            return urlunparse(("https", "api.openai.com", "/v1", "", "", ""))

    return value.rstrip("/")

# Resolved at import for backwards compatibility; prefer get_chat_model() at call sites.
DEFAULT_CHAT_MODEL = get_chat_model()
SUPPORTED_CHAT_MODELS = {
    "gpt-4.1-mini",
    "gpt-4.1",
    "openai/gpt-oss-120b-mini",
    "openai/gpt-oss-120b",
    "o4-mini",
    "o4",
    "o3-mini",
    # add (won't hurt even if you route it to Responses)
    "openai/gpt-oss-120b",
}

MODEL_ALIASES = {
    "openai/gpt-oss-120b": "openai/gpt-oss-120b",
    "openai/gpt-oss-120bpro": "openai/gpt-oss-120b",
    "gpt5.2pro": "openai/gpt-oss-120b",
    "openai/gpt-oss-120bpro-plus": "openai/gpt-oss-120b",
}

# Maximum tool-call rounds before forcing a final text response
MAX_TOOL_CALL_ROUNDS = 8

# ======================================================================
# Prompt injection sanitizer for external content
# ======================================================================
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


_RESEARCH_STOPWORDS = {
    "the", "and", "or", "but", "is", "are", "was", "were", "a", "an", "to", "of",
    "in", "for", "on", "with", "by", "as", "at", "from", "that", "this", "it",
    "be", "can", "could", "should", "would", "about", "into", "over", "after",
    "before", "between", "latest", "newest", "recent", "current", "today",
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

# Keywords that indicate the user query is security/hacking related and
# should activate the full offensive persona prompts.  General queries
# (e.g. "newest iphone", "best laptop 2026") must NOT trigger this.
_SECURITY_QUERY_HINTS = (
    *_REDTEAM_HINTS,
    "reverse shell",
    "webshell",
    "web shell",
    "malware",
    "nmap",
    "wireshark",
    "burp",
    "hack",
    "vuln",
    "attack",
    "recon",
    "shell",
    "spoof",
    "phish",
    "rootkit",
    "keylogger",
    "ransomware",
    "rat ",
    "trojan",
    "backdoor",
    "privilege escalation",
    "priv esc",
    "privesc",
    "lateral movement",
    "post-exploitation",
    "post exploitation",
    "buffer overflow",
    "bufferoverflow",
    "sql injection",
    "sqli",
    "xss",
    "cross-site",
    "csrf",
    "ssrf",
    "rce",
    "remote code execution",
    "command injection",
    "lfi",
    "rfi",
    "directory traversal",
    "path traversal",
    "deserialization",
    "c2",
    "command and control",
    "msfvenom",
    "cobalt strike",
    "mimikatz",
    "bloodhound",
    "hashcat",
    "john the ripper",
    "hydra",
    "gobuster",
    "dirb",
    "nikto",
    "sqlmap",
    "waf bypass",
    "evasion",
    "kali",
    "parrot os",
    "ctf",
    "capture the flag",
    "htb",
    "hackthebox",
    "tryhackme",
    "oscp",
    "owasp",
    "dark_recon",
)

# define for injection auto.
def _is_security_query(messages: list) -> bool:
    """
    Check if the latest user message is security/hacking related.
    Returns True if offensive persona prompts should be included.
    """
    user_text = ""
    for m in reversed(messages or []):
        if m.get("role") == "user" and m.get("content"):
            user_text = str(m["content"]).strip().lower()
            break
    if not user_text:
        return False
    return any(hint in user_text for hint in _SECURITY_QUERY_HINTS)



# Add this decorator definition (preferably near the top, after imports)
def log_method(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Log under the *instance* class module so subclasses (e.g. XaiLLMAdvisor
        # in xai_client) do not appear as src.llm.openai_client in the logs.
        if args:
            cls = args[0].__class__
            cls_name = cls.__name__
            log = logging.getLogger(cls.__module__)
        else:
            cls_name = func.__module__
            log = logger
        method_name = func.__name__
        log.info(
            f"[ENTER] {cls_name}.{method_name}  args={args[1:]!r}  kwargs={kwargs!r}"
        )
        try:
            result = func(*args, **kwargs)
            log.info(
                f"[EXIT]  {cls_name}.{method_name}  →  {result!r:.120}"
            )
            return result
        except Exception as exc:
            tb = traceback.format_exc()
            log.error(
                f"[ERROR] {cls_name}.{method_name}  raised={exc!r}\n{tb}"
            )
            raise
    return wrapper
# ----------------------------------------------------------------------
# PLANNER IMPLEMENTATION (added as per request)
# ----------------------------------------------------------------------
def _auto_answer_questions(questions: List[Dict[str, str]]) -> Dict[str, str]:
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
    from src.tools.registry import dispatch_tool_call
    import datetime as _dt

    llm_log = _setup_daily_llm_logger()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model_name = get_chat_model()

    # -----------------------------------------------------------------
    # 1. Draft plan
    # -----------------------------------------------------------------
    logger.info("=== STEP 1 - Draft plan ===")
    try:
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "event": "llm_request",
            "layer": "planner_draft",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "user_request_len": len(user_request or ""),
        }, ensure_ascii=False))
    except Exception:
        pass

    # Single-layer path via PromptEngine (backward-compatible system+user strings)
    from src.prompts.layers import build_planner_prompts

    _planner_draft = build_planner_prompts(user_request=user_request, with_evidence=False)
    draft_raw = call_llm(
        system_prompt=_planner_draft.system,
        user_prompt=_planner_draft.user or user_request,
    )

    # Log draft result
    try:
        draft_text = json.dumps(draft_raw, ensure_ascii=False, default=str)[:10_000] if draft_raw else ""
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "event": "llm_response",
            "layer": "planner_draft",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "text": draft_text,
        }, ensure_ascii=False))
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
    search_result = dispatch_tool_call("research_search", {
        "queries": queries,
        "max_results_per_query": 10,
    })

    raw_results = search_result.get("results", [])
    logger.info(
        "Planner research_search: %d queries -> %d results",
        len(queries), len(raw_results),
    )

    # Log research step
    try:
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "event": "llm_research",
            "layer": "planner_research",
            "queries_count": len(queries),
            "results_count": len(raw_results),
            "queries": [str(q)[:200] for q in queries],
        }, ensure_ascii=False))
    except Exception:
        pass

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

    try:
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "event": "llm_request",
            "layer": "planner_synthesis",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "evidence_count": len(evidence_items),
        }, ensure_ascii=False))
    except Exception:
        pass

    from src.prompts.layers import build_planner_prompts

    _planner_final = build_planner_prompts(
        user_request=user_request,
        with_evidence=True,
        evidence_variables={
            "user_request": user_request,
            "research_results_json": json.dumps(evidence_items, ensure_ascii=False, default=str),
            "synthesis_prompt": synthesis_prompt,
        },
    )
    final_raw = call_llm(
        system_prompt=_planner_final.system,
        user_prompt=_planner_final.user or synthesis_prompt,
    )

    # Log synthesis result
    try:
        final_text = json.dumps(final_raw, ensure_ascii=False, default=str)[:10_000] if final_raw else ""
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "event": "llm_response",
            "layer": "planner_synthesis",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "text": final_text,
        }, ensure_ascii=False))
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

# ----------------------------------------------------------------------
# END OF PLANNER INTEGRATION
# ----------------------------------------------------------------------


class _ResearchHTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._texts: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data) -> None:
        if not self._skip:
            self._texts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._texts)).strip()


def _research_tokenize(text: str) -> List[str]:
    tokens = [t for t in re.findall(r"[a-zA-Z0-9]+", (text or "").lower()) if t]
    return [t for t in tokens if t not in _RESEARCH_STOPWORDS]


def _research_extract_keywords(text: str, max_keywords: int = 8) -> List[str]:
    tokens = _research_tokenize(text)
    seen = set()
    out: List[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_keywords:
            break
    return out


def _research_stable_unique(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _research_expand_query_layers(keywords: List[str], user_text: str) -> Dict[str, List[str]]:
    layer_a = []
    if user_text:
        layer_a.append(user_text.strip())
    if keywords:
        layer_a.append(" ".join(keywords[:3]).strip())
        layer_a.append(" ".join(keywords[:4]).strip())

    layer_b = []
    for k in keywords:
        syns = _RESEARCH_SYNONYMS.get(k, [])
        for s in syns:
            layer_b.append(f"{s} {k}")
    if not layer_b and keywords:
        layer_b = [f"{k} overview" for k in keywords[:3]]

    layer_c = []
    for k in keywords[:3]:
        layer_c.append(f"site:gov {k}")
        layer_c.append(f"site:edu {k}")
        layer_c.append(f"filetype:pdf {k}")
    layer_c.extend(["site:who.int", "site:europa.eu"])
    return {
        "layer_a": _research_stable_unique(layer_a),
        "layer_b": _research_stable_unique(layer_b),
        "layer_c": _research_stable_unique(layer_c),
    }


def _research_sanitize_query(q: str, *, max_len: int = 160) -> str:
    q = re.sub(r"\s+", " ", (q or "")).strip()
    if len(q) > max_len:
        q = q[:max_len].strip()
    return q


def _research_parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    try:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return None


def _research_parse_targets(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        t = item.strip().lower()
        if t in _PLANNER_TARGETS and t not in out:
            out.append(t)
    return out


def _research_is_redteam_query(text: str, targets: Optional[List[str]] = None) -> bool:
    if targets and any(t in targets for t in ("cve", "exploit", "poc")):
        return True
    t = (text or "").lower()
    return any(h in t for h in _REDTEAM_HINTS)


def _research_needs_github_search(text: str, targets: Optional[List[str]] = None) -> bool:
    if targets and any(t in targets for t in ("github", "repo", "code")):
        return True
    t = (text or "").lower()
    return any(h in t for h in _GIT_REPO_HINTS)


def _research_expand_github_layers(
    base_queries: List[str],
    user_text: str,
    keywords: List[str],
    *,
    redteam: bool = False,
    max_queries: int = 8,
) -> List[str]:
    seeds: List[str] = []
    for q in base_queries or []:
        s = _research_sanitize_query(q)
        if s and s not in seeds:
            seeds.append(s)
    if not seeds and user_text:
        seeds.append(_research_sanitize_query(user_text))
    if not seeds and keywords:
        seeds.append(_research_sanitize_query(" ".join(keywords[:4])))

    suffixes = ["repo"]
    if redteam:
        suffixes.extend(["exploit", "poc", "cve"])

    queries: List[str] = []
    for seed in seeds:
        if not seed:
            continue
        queries.append(f"site:github.com {seed}")
        for suf in suffixes:
            if len(queries) >= max_queries:
                break
            queries.append(f"site:github.com {seed} {suf}")
        if len(queries) >= max_queries:
            break
    return _research_stable_unique(queries)[:max_queries]


def _research_detect_missing_package_version(text: str) -> bool:
    t = (text or "").lower()
    indicators = [
        "not in dataset", "not in the dataset", "version not in dataset",
        "version not found", "unknown version", "not found in dataset",
        "not in training data", "new version", "latest version",
        "out of date dataset", "dataset is old",
    ]
    package_hints = [
        "package", "module", "library", "dependency", "pip", "npm", "pypi",
        "crate", "crates", "maven", "nuget", "gem", "rubygem", "packagist",
    ]
    return any(i in t for i in indicators) and any(h in t for h in package_hints)


def _research_guess_package_name(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"(?:package|module|library|dependency)\s+([A-Za-z0-9_.-]+)",
        r"(?:pip3?\s+install|pipx\s+install)\s+([A-Za-z0-9_.-]+)",
        r"(?:npm\s+install|yarn\s+add|pnpm\s+add)\s+([A-Za-z0-9_.-]+)",
        r"(?:cargo\s+add)\s+([A-Za-z0-9_.-]+)",
        r"(?:go\s+get)\s+([A-Za-z0-9_./-]+)",
        r"(?:gem\s+install)\s+([A-Za-z0-9_.-]+)",
        r"(?:dotnet\s+add\s+package)\s+([A-Za-z0-9_.-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _research_extend_layers_for_package(layers: Dict[str, List[str]], package_name: Optional[str]) -> Dict[str, List[str]]:
    if not package_name:
        return layers
    layer_b = list(layers.get("layer_b") or [])
    layer_c = list(layers.get("layer_c") or [])

    layer_b.extend([
        f"{package_name} latest version",
        f"{package_name} release notes",
        f"{package_name} changelog",
        f"{package_name} install instructions",
        f"{package_name} documentation",
    ])

    for domain in _RESEARCH_PACKAGE_REGISTRIES:
        layer_c.append(f"site:{domain} {package_name}")

    layers["layer_b"] = _research_stable_unique(layer_b)
    layers["layer_c"] = _research_stable_unique(layer_c)
    return layers


def _research_is_latest_query(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("latest", "newest", "recent", "current", "today"))


def _research_canonicalize_url(url: str) -> str:
    if url.startswith("MISSING_RESULT_"):
        return url
    try:
        p = urlparse(url)
        scheme = (p.scheme or "http").lower()
        netloc = (p.netloc or "").lower()
        path = p.path or ""
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_")]
        query = urlencode(sorted(query))
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return url


def _research_extract_domain(url: str) -> str:
    if url.startswith("MISSING_RESULT_"):
        return url
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _research_extract_title(html_text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text or "", re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _research_strip_html(html_text: str) -> str:
    parser = _ResearchHTMLStripper()
    parser.feed(html_text or "")
    text = parser.get_text()
    # Sanitize extracted text against prompt injection patterns
    text = _sanitize_external_content(text, label="web")
    return text


def _research_extract_date(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.findall(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if m:
        y, mo, d = m[0]
        try:
            return datetime.date(int(y), int(mo), int(d)).isoformat()
        except Exception:
            pass
    m2 = re.findall(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2}),\s+(20\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if m2:
        mon, day, year = m2[0]
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        try:
            mo = months[mon.strip().lower()[:3]]
            return datetime.date(int(year), int(mo), int(day)).isoformat()
        except Exception:
            pass
    return None


def _research_compute_recency_score(date_str: Optional[str]) -> float:
    if not date_str:
        return 0.0
    try:
        d = datetime.date.fromisoformat(date_str)
    except Exception:
        return 0.0
    days = (datetime.date.today() - d).days
    if days < 0:
        days = 0
    return max(0.0, 1.0 - min(days, 365) / 365.0)


def _research_compute_reliability_score(url: str, title: str) -> float:
    domain = _research_extract_domain(url)
    score = 0.3
    if domain.endswith((".gov", ".edu", ".mil", ".int")):
        score += 0.4
    if domain.endswith(("who.int", "europa.eu")):
        score += 0.2
    if "official" in (title or "").lower() or "press" in (title or "").lower():
        score += 0.05
    if "blog" in domain:
        score -= 0.05
    return max(0.0, min(1.0, score))


def _research_split_claims(text: str, max_claims: int = 3) -> List[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    claims = [p.strip() for p in parts if len(p.strip()) >= 20]
    return claims[:max_claims]


def _research_jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _research_pdf_to_text_if_available(pdf_bytes: bytes) -> Optional[str]:
    if not pdf_bytes:
        return None
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return None
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "doc.pdf")
        txt_path = os.path.join(tmpdir, "doc.txt")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        try:
            subprocess.check_call([pdftotext, pdf_path, txt_path],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
        except Exception:
            return None
    return None


class DailyFileHandler(logging.Handler):
    """Daily log file handler that writes to:
    <log_dir>/llm-YYYY-MM-DD.log
    - If today's file exists, it appends.
    - If not, it creates it.
    - Switches file automatically when local date changes.
    """

    def __init__(self, log_dir: Path, prefix: str = "llm", encoding: str = "utf-8") -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.prefix = prefix
        self.encoding = encoding
        self._lock = threading.RLock()
        self._current_date: Optional[str] = None
        self._fp = None

        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _today_path(self) -> Path:
        ds = datetime.date.today().isoformat()  # YYYY-MM-DD
        return self.log_dir / f"{self.prefix}-{ds}.log"

    def _ensure_file(self) -> None:
        ds = datetime.date.today().isoformat()
        if self._current_date == ds and self._fp:
            return

        if self._fp:
            try:
                self._fp.flush()
                self._fp.close()
            except Exception:
                pass
            self._fp = None

        path = self._today_path()
        self._fp = path.open("a", encoding=self.encoding)
        self._current_date = ds

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self._ensure_file()
                assert self._fp is not None
                self._fp.write(msg + "\n")
                self._fp.flush()
        except Exception:
            # never crash the app because of logging
            pass


def _setup_daily_llm_logger() -> logging.Logger:
    """Dedicated logger for LLM traces that writes one file per day.

    Location:
      - env LLM_LOG_DIR if set
      - else <BASE_DIR>/logs/llm
    """
    log_dir_env = os.getenv("LLM_LOG_DIR")
    if log_dir_env:
        log_dir = Path(log_dir_env).expanduser()
    else:
        log_dir = (BASE_DIR / "logs" / "llm")

    llm_logger = logging.getLogger("mrrobot.llm")
    llm_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on reloads
    if any(isinstance(h, DailyFileHandler) for h in llm_logger.handlers):
        return llm_logger

    h = DailyFileHandler(log_dir=log_dir, prefix="llm")
    h.setFormatter(logging.Formatter("%(message)s"))  # JSONL line per entry
    llm_logger.addHandler(h)
    llm_logger.propagate = False
    return llm_logger


class LLMConfig(BaseModel):
    enabled: bool
    model: str
    max_tokens: int = 65536
    temperature: float = 0.5
    top_p: float = 1.0
    assistant_id: Optional[str] = None

    # <-- NEW FLAG: turn planner on/off globally
    enable_planner: bool = True   # set to False to disable

    # --- NEW: web search / internet access ---
    enable_web_search: bool = False
    web_search_external_access: bool = True  # True = live internet, False = cached/offline

    # Optional explicit provider override ("openai" | "xai"). When None, the
    # router auto-detects from the model name / LLM_PROVIDER env.
    provider: Optional[str] = None

def load_llm_config(config_dir: Path) -> LLMConfig:
    import yaml

    app_yaml = config_dir / "app.yaml"
    with app_yaml.open() as f:
        data = yaml.safe_load(f) or {}

    llm_cfg = data.get("llm", {})

    # Env takes precedence over app.yaml so models can be switched without editing config.
    env_model = os.getenv("OPENAI_DEFAULT_CHAT_MODEL") or os.getenv("LLM_MODEL")
    model = (env_model or llm_cfg.get("model") or get_chat_model()).strip()

    # Explicit provider: LLM_PROVIDER env wins over app.yaml llm.provider.
    env_provider = (os.getenv("LLM_PROVIDER") or "").strip() or None
    yaml_provider = llm_cfg.get("provider")
    provider = env_provider or (str(yaml_provider).strip() if yaml_provider else None)

    # Hard-cap: values like 999999… break some providers and bloat logs.
    raw_max = int(llm_cfg.get("max_tokens", 4096))
    max_tokens = max(1, min(raw_max, 65536))
    if raw_max != max_tokens:
        logger.warning(
            "llm.max_tokens=%s is out of range; clamping to %s",
            raw_max,
            max_tokens,
        )

    return LLMConfig(
        enabled=bool(llm_cfg.get("enabled", False)),
        model=str(model),
        max_tokens=max_tokens,
        temperature=float(llm_cfg.get("temperature", 0.2)),
        top_p=float(llm_cfg.get("top_p", 1.0)),
        assistant_id=str(llm_cfg.get("assistant_id")).strip() or None
        if llm_cfg.get("assistant_id")
        else None,
        # <-- NEW: read the planner flag
        enable_planner=bool(llm_cfg.get("enable_planner", True)),
        # --- NEW ---
        enable_web_search=bool(llm_cfg.get("enable_web_search", False)),
        web_search_external_access=bool(llm_cfg.get("web_search_external_access", True)),
        provider=provider,
    )

class OpenAILLMAdvisor:
    """Defensive-only advisor.

    - Summarizes scanner outputs.
    - Explains risk in human-readable form.
    - Suggests mitigations and secure coding practices.
    - Does NOT emit exploit code, payloads, or attack chains.
    """

    _SCRIPT_LANG_ALIASES = {
        "bash": "bash",
        "sh": "bash",
        "zsh": "bash",
        "shell": "bash",
        "python": "python",
        "py": "python",
        "python3": "python",
        "ruby": "ruby",
        "rb": "ruby",
        "js": "js",
        "javascript": "js",
        "node": "js",
        "nodejs": "js",
        "deno": "js",
    }
    @log_method
    def __init__(self, config: LLMConfig):
        self.config = config

        self.llm_logger = _setup_daily_llm_logger()
        if not self.config.enabled:
            self.client = None
            return

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment")
        # Explicit timeout so hung NVIDIA/OpenAI calls fail instead of
        # sitting silent after _should_use_responses_api with no EXIT log.
        # OPENAI_TIMEOUT seconds (default 180). Prefer explicit base_url when set.
        _timeout = float(os.getenv("OPENAI_TIMEOUT", "180"))
        base_url = normalize_openai_base_url(os.getenv("OPENAI_BASE_URL"))
        self._api_base_url = base_url
        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=_timeout)
        else:
            self.client = OpenAI(api_key=api_key, timeout=_timeout)

    @property
    def _log(self) -> logging.Logger:
        """Logger bound to the concrete class module (OpenAI vs xAI)."""
        return logging.getLogger(self.__class__.__module__)

    def _get_model_name(self) -> str:
        raw = (self.config.model or get_chat_model()).strip()
        aliased = MODEL_ALIASES.get(raw, raw)
        # OpenRouter requires vendor-prefixed ids: openai/<model>
        try:
            from src.llm.router import normalize_model_for_provider

            base = getattr(self, "_api_base_url", None) or os.getenv("OPENAI_BASE_URL")
            return normalize_model_for_provider(
                aliased,
                "openai",
                base_url=base,
            )
        except Exception:
            return aliased

    def _responses_supports_sampling(self, model_name: str) -> bool:
        """Conservative: GPT-5.* models commonly reject temperature/top_p on Responses.
        Only enable sampling for models you have verified accept it.
        """
        if model_name.startswith("gpt-5"):
            return False
        return True
    @staticmethod
    def _clean_inbound_text(text: Optional[str], *, max_len: int = 24_000) -> Optional[str]:
        """Normalize and sanitize pass-through prompts/messages.

        - Truncates to ``max_len`` to prevent huge payloads.
        - Strips prompt injection patterns from externally-provided text.
        """
        if text is None:
            return None
        t = str(text).strip()
        if not t:
            return None
        if len(t) > max_len:
            t = t[:max_len] + "\n...[TRUNCATED]..."
        # Sanitize potential prompt injections from API callers
        t = _sanitize_external_content(t, label="api-input")
        return t

    @classmethod
    def _normalize_lang_tag(cls, lang: Optional[str]) -> Optional[str]:
        if not lang:
            return None
        key = str(lang).strip().lower()
        if not key:
            return None
        return cls._SCRIPT_LANG_ALIASES.get(key, key)
    @classmethod
    def _is_script_line(cls, line: str) -> bool:
        s = line.strip()
        if not s:
            return False
        if re.match(r"^#!.*\b(bash|sh|zsh|python|python3|ruby|node|nodejs|deno)\b", s, re.I):
            return True
        if re.match(r"^\s*\$\s+", line):
            return True
        if re.match(r"^\s*(def|class)\s+\w+", line):
            return True
        if re.match(r"^\s*(import|from)\s+\w+", line):
            return True
        if re.match(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:", line):
            return True
        if re.match(r"^\s*(module|require|puts)\b", line):
            return True
        if re.match(r"^\s*(const|let|var|function|async\s+function|import|export)\b", line):
            return True
        if re.match(r"^\s*console\.log\b", line):
            return True
        if re.match(
            r"^\s*(sudo|apt(?:-get)?|yum|dnf|brew|apk|pacman|curl|wget|chmod|chown|mkdir|rm|cp|mv|cat|echo|printf|grep|sed|awk|ssh|scp|tar|zip|unzip|git|python|python3|ruby|node|npm|npx)\b",
            line,
        ):
            return True
        if re.match(r"^\s*\w+\s*=\s*[^=]+$", line):
            return True
        return False
    @classmethod
    def _guess_script_language(cls, lines: List[str]) -> Optional[str]:
        scores = {"bash": 0, "python": 0, "ruby": 0, "js": 0}
        strong_bash = False
        for line in lines:
            s = line.strip()
            if not s:
                continue
            m = re.match(r"^#!.*\b(?P<lang>bash|sh|zsh|python|python3|ruby|node|nodejs|deno)\b", s, re.I)
            if m:
                return cls._normalize_lang_tag(m.group("lang"))
            if re.match(r"^\s*(def|class)\s+\w+", line):
                scores["python"] += 2
                scores["ruby"] += 2
            if re.match(r"^\s*(import|from)\s+\w+", line):
                scores["python"] += 2
            if re.match(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:", line):
                scores["python"] += 3
            if re.match(r"^\s*(module|require|puts)\b", line):
                scores["ruby"] += 2
            if re.match(r"^\s*(const|let|var|function|async\s+function|import|export)\b", line):
                scores["js"] += 2
            if re.match(r"^\s*console\.log\b", line):
                scores["js"] += 2
            if re.match(r"^\s*\$\s+", line):
                scores["bash"] += 2
                strong_bash = True
            if re.match(
                r"^\s*(sudo|apt(?:-get)?|yum|dnf|brew|apk|pacman|curl|wget|chmod|chown|mkdir|rm|cp|mv|cat|echo|printf|grep|sed|awk|ssh|scp|tar|zip|unzip|git|python|python3|ruby|node|npm|npx)\b",
                line,
            ):
                scores["bash"] += 1
                strong_bash = True
            if re.match(r"^\s*\w+\s*=\s*[^=]+$", line):
                scores["bash"] += 1
        lang, score = max(scores.items(), key=lambda kv: kv[1])
        if score == 0:
            return None
        if score == 1 and not strong_bash:
            return None
        return lang
    @classmethod
    def _wrap_loose_script_blocks(cls, text: str) -> str:
        if not text:
            return text
        lines = text.splitlines()
        out: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if cls._is_script_line(line):
                block: List[str] = []
                while i < len(lines):
                    line = lines[i]
                    if cls._is_script_line(line):
                        block.append(line)
                        i += 1
                        continue
                    if not line.strip() and i + 1 < len(lines) and cls._is_script_line(lines[i + 1]):
                        block.append(line)
                        i += 1
                        continue
                    break
                lang = cls._guess_script_language(block)
                if lang:
                    out.append(f"[code {lang}]")
                    out.extend(block)
                    out.append("[/code]")
                else:
                    out.extend(block)
            else:
                out.append(line)
                i += 1
        return "\n".join(out)
    @classmethod
    def _normalize_code_blocks(cls, text: str) -> str:
        if not text:
            return text
        lines = text.splitlines()
        out_lines: List[str] = []
        text_buffer: List[str] = []
        in_code = False
        fence_type: Optional[str] = None
        code_lang: Optional[str] = None

        def flush_text() -> None:
            if not text_buffer:
                return
            wrapped = cls._wrap_loose_script_blocks("\n".join(text_buffer))
            out_lines.extend(wrapped.splitlines())
            text_buffer.clear()

        def emit_code_open(lang: Optional[str]) -> None:
            if lang:
                out_lines.append(f"[code {lang}]")
            else:
                out_lines.append("[code]")

        for line in lines:
            bb_open = re.match(r"^\[code(?:(?:=|\s+)([A-Za-z0-9_-]+))?\]\s*$", line, re.I)
            bb_close = re.match(r"^\[/code\]\s*$", line, re.I)
            md_open = re.match(r"^```(\w+)?\s*$", line)
            md_close = re.match(r"^```\s*$", line)

            if not in_code and (bb_open or md_open):
                flush_text()
                in_code = True
                fence_type = "bbcode" if bb_open else "markdown"
                code_lang = cls._normalize_lang_tag((bb_open.group(1) if bb_open else md_open.group(1)))
                emit_code_open(code_lang)
                continue

            if in_code:
                if (fence_type == "bbcode" and bb_close) or (fence_type == "markdown" and md_close):
                    out_lines.append("[/code]")
                    in_code = False
                    fence_type = None
                    code_lang = None
                    continue
                out_lines.append(line)
                continue

            text_buffer.append(line)

        if in_code:
            out_lines.append("[/code]")
        else:
            flush_text()

        return "\n".join(out_lines)

    def _web_search_enabled(self) -> bool:
        # Allow env override without changing YAML
        env = os.getenv("LLM_ENABLE_WEB_SEARCH", "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            return True
        return bool(getattr(self.config, "enable_web_search", False))

    def _is_openai_backend(self) -> bool:
        """Heuristic: if you're using the official OpenAI endpoint, base_url is empty or openai.com."""
        base_url = os.getenv("OPENAI_BASE_URL", "").strip().lower()
        if not base_url:
            return True
        return "openai.com" in base_url

    def _backend_supports_web_search_tool(self) -> bool:
        # Hosted web_search is an OpenAI hosted tool; most compatibles don't implement it.
        return self._is_openai_backend()

    def _backend_supports_reasoning(self) -> bool:
        """Only real OpenAI supports the ``reasoning`` parameter with ``summary``."""
        return self._is_openai_backend()
    @staticmethod
    def _extract_section(text: str, title: str) -> str:
        """Extract a section body by title."""
        if not text:
            return ""
        t = str(text)
        title_re = re.escape(title)
        pattern = re.compile(
            rf"(?ims)"
            rf"(?:^|\n)\s*"
            rf"(?:#{1,6}\s*|\*\*)?"
            rf"{title_re}"
            rf"(?:\*\*)?\s*:?"
            rf"\s*\n?"
            rf"(.*?)"
            rf"(?=\n\s*(?:#{1,6}\s+\S|\*\*\w|---|\Z))"
        )
        m = pattern.search(t)
        if not m:
            return ""
        return (m.group(1) or "").strip()
    @log_method
    def _log_research_event(
        self,
        stage: str,
        payload: Dict[str, Any],
        *,
        max_len: int = 1200,
        max_list: int = 50,
    ) -> None:
        try:
            safe_payload: Dict[str, Any] = {}
            for k, v in (payload or {}).items():
                if isinstance(v, str):
                    safe_payload[k] = self._clean_inbound_text(v, max_len=max_len) or ""
                elif isinstance(v, list) and len(v) > max_list:
                    safe_payload[k] = v[:max_list]
                else:
                    safe_payload[k] = v
            data = {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "event": "llm_research",
                "stage": stage,
                "payload": safe_payload,
            }
            self.llm_logger.info(json.dumps(data, ensure_ascii=False))
            audit_log("llm_research", {"stage": stage, **safe_payload})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Unified LLM-interaction logger – captures response, reasoning,
    # thinking, and token usage for ANY layer / API variant.
    # Works with OpenAI, NVIDIA NIM, and any compatible backend.
    # ------------------------------------------------------------------
    def _log_llm_interaction(
        self,
        *,
        layer: str,
        api: str,
        model: str,
        output_text: str,
        resp: Any = None,
        response: Any = None,
        extra: Optional[Dict[str, Any]] = None,
        elapsed_ms: Optional[float] = None,
    ) -> None:
        """Log a **complete** LLM interaction to the daily JSONL logger.

        Every call produces three log lines:
          1. ``llm_response``  – full response text (up to 1 MB) + token usage
          2. ``llm_reasoning`` – full reasoning / chain-of-thought (up to 10 MB)
          3. ``llm_thinking``  – embedded ``<thinking>`` section from output

        Parameters
        ----------
        layer : str
            Logical layer name, e.g. ``"secure_chat"``, ``"query_plan"``,
            ``"code_context"``, ``"tool_loop"``, ``"planner_draft"``, etc.
        api : str
            ``"responses"`` or ``"chat.completions"``.
        model : str
            Model identifier sent in the request.
        output_text : str
            The final text returned by the model.
        resp : Any, optional
            The raw Responses-API response object (when *api* = ``"responses"``).
        response : Any, optional
            The raw Chat Completions response object.
        extra : dict, optional
            Arbitrary extra fields to include in every log line.
        elapsed_ms : float, optional
            Wall-clock milliseconds the LLM call took (caller measured).
        """
        try:
            ts = datetime.datetime.now().isoformat(timespec="milliseconds")
            base_url = os.getenv("OPENAI_BASE_URL", "").strip()

            # ── Token usage ──
            usage_data: Dict[str, Any] = {}
            if api == "responses" and resp is not None:
                usage = getattr(resp, "usage", None)
                if usage:
                    usage_data = {
                        "tokens_total": getattr(usage, "total_tokens", None),
                        "tokens_prompt": getattr(usage, "input_tokens", None),
                        "tokens_completion": getattr(usage, "output_tokens", None),
                    }
            elif response is not None:
                usage = getattr(response, "usage", None)
                if usage:
                    usage_data = {
                        "tokens_total": getattr(usage, "total_tokens", None),
                        "tokens_prompt": getattr(usage, "prompt_tokens", None),
                        "tokens_completion": getattr(usage, "completion_tokens", None),
                    }

            common: Dict[str, Any] = {
                "layer": layer,
                "api": api,
                "model": model,
                "backend": base_url or "default",
            }
            if elapsed_ms is not None:
                common["elapsed_ms"] = elapsed_ms

            # ── 1) Full response text (1 MB cap) ──
            full_text = (output_text or "")[:1_000_000]
            if len(output_text or "") > 1_000_000:
                full_text += "...[TRUNCATED_AT_1MB]"
            self.llm_logger.info(json.dumps({
                "ts": ts,
                "event": "llm_response",
                **common,
                **usage_data,
                "text_length": len(output_text or ""),
                "text": full_text,
                **(extra or {}),
            }, ensure_ascii=False))

            # ── 2) Full reasoning / summary (10 MB cap) ──
            reasoning = ""
            if api == "responses" and resp is not None:
                reasoning = self.extract_reasoning_summary_from_response(resp)
            elif response is not None:
                try:
                    msg = response.choices[0].message if response.choices else None
                    if msg:
                        reasoning = getattr(msg, "reasoning", None) or ""
                        if not reasoning:
                            reasoning = getattr(msg, "reasoning_content", None) or ""
                except Exception:
                    pass
            full_reasoning = (str(reasoning) if reasoning else "")[:10_000_000]
            self.llm_logger.info(json.dumps({
                "ts": ts,
                "event": "llm_reasoning",
                **common,
                "missing": not bool(full_reasoning),
                "reasoning_length": len(str(reasoning) if reasoning else ""),
                "reasoning": full_reasoning,
            }, ensure_ascii=False))

            # ── 3) Thinking section (embedded in output text) ──
            thinking = ""
            if hasattr(self, "_extract_section"):
                thinking = self._extract_section(output_text or "", "Thinking")
            self.llm_logger.info(json.dumps({
                "ts": ts,
                "event": "llm_thinking",
                **common,
                "missing": not bool(thinking),
                "thinking_length": len(thinking) if thinking else 0,
                "thinking": thinking if thinking else None,
            }, ensure_ascii=False))

            # ── Audit log ──
            audit_log("llm_call", {
                **common,
                **usage_data,
                "text_length": len(output_text or ""),
                "reasoning_length": len(str(reasoning) if reasoning else ""),
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # The rest of OpenAILLMAdvisor methods remain unchanged...
    # (All existing methods from the original file are retained here.)
    # ------------------------------------------------------------------

    # ... (the rest of the class implementation continues unchanged)
    # For brevity, the remaining methods from the original file are omitted
    # but are assumed to be present exactly as in the original source.
    @log_method
    def _pre_search_llm_query_plan(self, user_text: str) -> Dict[str, Any]:
        plan: Dict[str, Any] = {"needs_search": False, "queries": [], "reason": ""}
        if not self.config.enabled or self.client is None:
            return plan

        raw = self._clean_inbound_text(user_text, max_len=4000) or ""
        if not raw:
            return plan

        model_name = self._get_model_name()
        output_text = ""
        search_prompt = (self._get_search_query_prompt() or "").strip()
        date_hint = (
            f"Today date: {datetime.date.today().isoformat()}. "
            "Use this to interpret 'latest/current/today' and to choose the year in queries."
        )
        search_prompt_with_date = f"{search_prompt}\n\n{date_hint}"

        _api_type = ""
        _resp_obj = None
        _chat_resp_obj = None
        try:
            if self._should_use_responses_api(model_name):
                _api_type = "responses"
                create_kwargs: Dict[str, Any] = {
                    "model": model_name,
                    "instructions": search_prompt_with_date,
                    "input": [
                    {
                    "role": "system",
                    "content": search_prompt_with_date,
                    },
                    {"role": "user", "content": raw},
                    ],  
                    "max_output_tokens": 512,
                }
                if self._responses_supports_sampling(model_name):
                    create_kwargs["temperature"] = 0
                    create_kwargs["top_p"] = 1
                resp = self.client.responses.create(**create_kwargs)
                _resp_obj = resp
                output_text = self._extract_responses_text(resp) or ""
            else:
                _api_type = "chat.completions"
                messages: List[Dict[str, str]] = [
                {
                    "role": "system",
                    "content": search_prompt_with_date,
                },
                {"role": "user", "content": raw},
                ]
                resp = self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0,
                    top_p=1,
                )
                _chat_resp_obj = resp
                output_text = resp.choices[0].message.content or ""
        except Exception as e:
            self._log_research_event(
                "STAGE_0_LLM_QUERY_PLAN_ERROR",
                {"error": str(e)},
            )
            plan["error"] = str(e)
            return plan

        # ── Full LLM interaction log (response + reasoning + tokens) ──
        self._log_llm_interaction(
            layer="query_plan",
            api=_api_type,
            model=model_name,
            output_text=output_text,
            resp=_resp_obj,
            response=_chat_resp_obj,
        )

        empty_output = not (output_text or "").strip()
        if empty_output:
            self._log_research_event(
                "STAGE_0_LLM_QUERY_PLAN_EMPTY_OUTPUT",
                {"raw_user_text": raw},
                max_len=10_000,
            )

        parsed = _research_parse_json_object(output_text) if not empty_output else None
        if parsed is None:
            fallback_q = _research_sanitize_query(raw)
            if fallback_q:
                plan = {
                    "needs_search": True,
                    "queries": [fallback_q],
                    "targets": [],
                    "reason": "empty_output" if empty_output else "fallback_parse",
                }
        else:
            needs_search = bool(parsed.get("needs_search"))
            queries_raw = parsed.get("queries") or []
            targets = _research_parse_targets(parsed.get("targets"))
            reason = str(parsed.get("reason") or "").strip()
            cleaned: List[str] = []
            if isinstance(queries_raw, list):
                for q in queries_raw:
                    if not isinstance(q, str):
                        continue
                    s = _research_sanitize_query(q)
                    if s and s not in cleaned:
                        cleaned.append(s)
                    if len(cleaned) >= 8:
                        break
            plan = {
                "needs_search": needs_search,
                "queries": cleaned,
                "targets": targets,
                "reason": reason,
            }

        self._log_research_event(
            "STAGE_0_LLM_QUERY_PLAN",
            {
                "needs_search": bool(plan.get("needs_search")),
                "queries": plan.get("queries", [])[:6],
                "targets": plan.get("targets", [])[:8],
                "reason": str(plan.get("reason") or ""),
            },
        )
        self._log_research_event(
            "STAGE_0_LLM_QUERY_PLAN_FULL",
            {
                "raw_user_text": raw,
                "raw_output": output_text,
                "parsed_plan": plan,
            },
            max_len=50_000,
        )
        return plan
    @log_method
    def _pre_search_code_context(self, user_text: str) -> Optional[Dict[str, Any]]:
        if not self.config.enabled or self.client is None:
            return None

        raw = self._clean_inbound_text(user_text, max_len=4000) or ""
        if not raw:
            return None

        model_name = self._get_model_name()
        output_text = ""
        code_prompt = (self._get_code_context_prompt() or "").strip()
        date_hint = (
            f"Today date: {datetime.date.today().isoformat()}. "
            "Use this to interpret 'latest/current/today' and to choose the year in queries."
        )
        code_prompt_with_date = f"{code_prompt}\n\n{date_hint}"

        _api_type = ""
        _resp_obj = None
        _chat_resp_obj = None
        try:
            if self._should_use_responses_api(model_name):
                _api_type = "responses"
                create_kwargs: Dict[str, Any] = {
                    "model": model_name,
                    "instructions": code_prompt_with_date,
                    "input": [
                        {
                            "role": "system",
                            "content": code_prompt_with_date,
                        },
                        {"role": "user", "content": raw},
                    ],
                    "max_output_tokens": 512,
                }
                if self._responses_supports_sampling(model_name):
                    create_kwargs["temperature"] = 0
                    create_kwargs["top_p"] = 1
                resp = self.client.responses.create(**create_kwargs)
                _resp_obj = resp
                output_text = self._extract_responses_text(resp) or ""
            else:
                _api_type = "chat.completions"
                messages: List[Dict[str, str]] = [
                    {
                        "role": "system",
                        "content": code_prompt_with_date,
                    },
                    {"role": "user", "content": raw},
                ]
                resp = self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0,
                    top_p=1,
                )
                _chat_resp_obj = resp
                output_text = resp.choices[0].message.content or ""
        except Exception as e:
            self._log_research_event(
                "STAGE_0_CODE_CONTEXT_PLAN_ERROR",
                {"error": str(e)},
            )
            return None

        # ── Full LLM interaction log (response + reasoning + tokens) ──
        self._log_llm_interaction(
            layer="code_context",
            api=_api_type,
            model=model_name,
            output_text=output_text,
            resp=_resp_obj,
            response=_chat_resp_obj,
        )

        empty_output = not (output_text or "").strip()
        if empty_output:
            self._log_research_event(
                "STAGE_0_CODE_CONTEXT_PLAN_EMPTY_OUTPUT",
                {"raw_user_text": raw},
                max_len=10_000,
            )
            return None

        parsed = _research_parse_json_object(output_text)
        if parsed is None:
            self._log_research_event(
                "STAGE_0_CODE_CONTEXT_PLAN_PARSE_ERROR",
                {"raw_output": output_text[:1000]},
                max_len=2_000,
            )
            return None

        code_related = bool(parsed.get("code_related"))
        needs_search = bool(parsed.get("needs_search"))
        queries_raw = parsed.get("queries") or []
        targets = _research_parse_targets(parsed.get("targets"))
        reason = str(parsed.get("reason") or "").strip()
        cleaned: List[str] = []
        if isinstance(queries_raw, list):
            for q in queries_raw:
                if not isinstance(q, str):
                    continue
                s = _research_sanitize_query(q)
                if s and s not in cleaned:
                    cleaned.append(s)
                if len(cleaned) >= 6:
                    break

        plan = {
            "code_related": code_related,
            "needs_search": needs_search,
            "queries": cleaned,
            "targets": targets,
            "reason": reason,
            "language": parsed.get("language") or "",
            "libraries": parsed.get("libraries") or [],
            "version": parsed.get("version") or "",
            "version_missing": bool(parsed.get("version_missing")),
        }

        self._log_research_event(
            "STAGE_0_CODE_CONTEXT_PLAN",
            {
                "code_related": code_related,
                "needs_search": needs_search,
                "queries": plan.get("queries", [])[:6],
                "targets": plan.get("targets", [])[:8],
                "version_missing": bool(plan.get("version_missing")),
                "language": str(plan.get("language") or ""),
                "reason": reason,
            },
        )
        self._log_research_event(
            "STAGE_0_CODE_CONTEXT_PLAN_FULL",
            {
                "raw_user_text": raw,
                "raw_output": output_text,
                "parsed_plan": plan,
            },
            max_len=50_000,
        )
        return plan
    @log_method
    def _pre_response_research_context(self, messages: List[Dict[str, str]]) -> Optional[str]:
        if not messages:
            return None

        user_text = ""
        for m in reversed(messages or []):
            if m.get("role") == "user" and m.get("content"):
                user_text = str(m.get("content")).strip()
                break
        if not user_text:
            return None

        plan = self._pre_search_llm_query_plan(user_text)
        plan_queries: List[str] = []
        plan_needs_search = False
        plan_targets: List[str] = []
        # -----------------------------------------------------------------
        # 3️⃣ PLANNER ACTIVATION (insert after extracting user_text)
        # -----------------------------------------------------------------
  
        if isinstance(plan, dict):
            plan_needs_search = bool(plan.get("needs_search"))
            for q in plan.get("queries") or []:
                if isinstance(q, str) and q.strip():
                    plan_queries.append(q.strip())
            for t in plan.get("targets") or []:
                if isinstance(t, str) and t.strip():
                    plan_targets.append(t.strip().lower())
        if plan_queries:
            plan_needs_search = True

        force_package_lookup = _research_detect_missing_package_version(user_text)

        code_plan: Optional[Dict[str, Any]] = None
        if (not plan_needs_search) or (not plan_queries) or force_package_lookup:
            code_plan = self._pre_search_code_context(user_text)
            if isinstance(code_plan, dict):
                code_needs_search = bool(code_plan.get("needs_search"))
                code_queries = [
                    q for q in (code_plan.get("queries") or [])
                    if isinstance(q, str) and q.strip()
                ]
                code_targets = [
                    t for t in (code_plan.get("targets") or [])
                    if isinstance(t, str) and t.strip()
                ]
                if code_needs_search and code_queries:
                    plan_needs_search = True
                    for q in code_queries:
                        if q not in plan_queries:
                            plan_queries.append(q)
                    for t in code_targets:
                        t_norm = t.strip().lower()
                        if t_norm and t_norm not in plan_targets:
                            plan_targets.append(t_norm)

        redteam_query = False
        github_query = False
        if plan_needs_search:
            redteam_query = _research_is_redteam_query(user_text, plan_targets)
            github_query = _research_needs_github_search(user_text, plan_targets) or redteam_query

        self._log_research_event(
            "STAGE_1_QUERY_DECOMPOSITION",
            {
                "user_text_len": len(user_text),
                "force_package_lookup": bool(force_package_lookup),
                "planner_needs_search": plan_needs_search,
                "planner_queries": len(plan_queries),
                "planner_targets": plan_targets[:8],
                "code_context_used": bool(code_plan),
                "code_context_needs_search": bool(code_plan.get("needs_search")) if code_plan else False,
                "code_context_version_missing": bool(code_plan.get("version_missing")) if code_plan else False,
                "redteam_query": redteam_query,
                "github_query": github_query,
            },
        )

        if not plan_needs_search and not force_package_lookup:
            self._log_research_event(
                "STAGE_1_SKIP_SEARCH",
                {
                    "reason": "planner_and_code_context_no_search",
                },
            )
            return None

        if not plan_queries:
            self._log_research_event(
                "STAGE_1_SKIP_SEARCH_NO_QUERIES",
                {
                    "reason": "no_llm_queries_available",
                    "force_package_lookup": bool(force_package_lookup),
                },
            )
            return None

        external_access = bool(self._web_search_enabled() or force_package_lookup) and bool(
            getattr(self.config, "web_search_external_access", True)
        )
        latest_bias = _research_is_latest_query(user_text)

        layers = {
            "layer_a": _research_stable_unique(plan_queries),
            "layer_b": [],
            "layer_c": [],
        }
        self._log_research_event(
            "STAGE_2_QUERY_EXPANSION_MULTI_LAYER",
            {
                "layer_a": len(layers.get("layer_a", [])),
                "layer_b": len(layers.get("layer_b", [])),
                "layer_c": len(layers.get("layer_c", [])),
            },
        )
        self._log_research_event(
            "STAGE_2_QUERY_EXPANSION_MULTI_LAYER_FULL",
            {
                "keywords": [],
                "layers": layers,
                "planner": plan,
                "code_context": code_plan,
                "planner_only": bool(plan_queries),
            },
            max_len=50_000,
        )

        results = self._research_collect_results(layers, external_access)
        missing_count = sum(1 for r in results if r.get("url", "").startswith("MISSING_RESULT_"))
        self._log_research_event(
            "STAGE_3_WEB_SEARCH_TOP_30",
            {
                "external_access": external_access,
                "results": len(results),
                "missing_results": missing_count,
            },
        )
        self._log_research_event(
            "STAGE_3_WEB_SEARCH_RESULTS_FULL",
            {"results": results},
            max_len=50_000,
        )
        extracts = self._research_fetch_and_extract(results[:10], external_access)
        self._log_research_event(
            "STAGE_4_FETCH_AND_EXTRACT",
            {
                "fetched": len(extracts),
                "skipped": sum(1 for e in extracts if e.get("skipped")),
            },
        )
        extracts_meta: List[Dict[str, Any]] = []
        for ex in extracts:
            extracts_meta.append(
                {
                    "url": ex.get("url"),
                    "title": ex.get("title"),
                    "date": ex.get("date"),
                    "content_type": ex.get("content_type"),
                    "skipped": ex.get("skipped"),
                    "error": ex.get("error"),
                    "text_len": len(ex.get("text") or ""),
                }
            )
        self._log_research_event(
            "STAGE_4_FETCH_AND_EXTRACT_META_FULL",
            {"extracts": extracts_meta},
            max_len=50_000,
        )
        evidence = self._research_rank_evidence(extracts, latest_bias)
        self._log_research_event(
            "STAGE_5_DEDUP_AND_RANK",
            {"evidence_entries": len(evidence), "latest_bias": latest_bias},
        )
        self._log_research_event(
            "STAGE_5_EVIDENCE_TABLE_FULL",
            {"evidence": evidence},
            max_len=50_000,
        )
        crosscheck = self._research_crosscheck(evidence)
        self._log_research_event(
            "STAGE_6_VALIDATE_AND_CROSSCHECK",
            {
                "verified_claims": len(crosscheck.get("verified", [])),
                "unverified_claims": len(crosscheck.get("unverified", [])),
            },
        )

        dates_found = [e.get("date") for e in evidence if e.get("date")]
        dates_found = sorted(set(dates_found), reverse=True)[:5]

        context = self._research_format_context(
            user_text=user_text,
            layers=layers,
            results=results,
            extracts=extracts,
            evidence=evidence,
            crosscheck=crosscheck,
            latest_bias=latest_bias,
            external_access=external_access,
            dates_found=dates_found,
        )
        self._log_research_event(
            "STAGE_7_ANALYZE_AND_SYNTHESIZE",
            {"context_ready": True, "dates_found": dates_found},
        )
        self._log_research_event(
            "STAGE_7_CONTEXT_FULL",
            {"context": context},
            max_len=100_000,
        )
        self._log_research_event(
            "STAGE_8_FINAL_ANSWER_WITH_CITATIONS",
            {"context_attached": True},
        )
        return context

    def _research_collect_results(self, layers: Dict[str, List[str]], external_access: bool) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        seen = set()

        if not external_access:
            for i in range(30):
                n = i + 1
                results.append({
                    "title": f"MISSING_RESULT_{n}",
                    "url": f"MISSING_RESULT_{n}",
                    "snippet": "",
                    "source": "placeholder",
                })
            return results

        rounds = [
            (layers.get("layer_a") or []) + (layers.get("layer_b") or []),
            (layers.get("layer_c") or []),
            (layers.get("layer_git") or []),
        ]

        _search_call_count = 0
        for query_list in rounds:
            for q in query_list:
                if not q:
                    continue
                # Rate-limit research searches to avoid DDG blocks that
                # would leave the tool-loop searches with no quota
                if _search_call_count > 0:
                    time.sleep(1.5)
                _search_call_count += 1
                try:
                    batch = web_search(q, max_results=10)
                except Exception as e:
                    self._log.warning("research web_search failed: %r", e)
                    self._log_research_event(
                        "SEARCH_ERROR",
                        {"query": q, "error": str(e)},
                    )
                    batch = []
                if not batch:
                    self._log_research_event(
                        "SEARCH_EMPTY",
                        {"query": q},
                    )

                for item in batch:
                    url = str(getattr(item, "url", "") or "").strip()
                    if not url:
                        continue
                    key = _research_canonicalize_url(url)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append({
                        "title": str(getattr(item, "title", "") or ""),
                        "url": url,
                        "snippet": str(getattr(item, "snippet", "") or ""),
                        "source": "ddgr",
                    })
                    if len(results) >= 30:
                        break
                if len(results) >= 30:
                    break
            if len(results) >= 30:
                break

        while len(results) < 30:
            n = len(results) + 1
            results.append({
                "title": f"MISSING_RESULT_{n}",
                "url": f"MISSING_RESULT_{n}",
                "snippet": "",
                "source": "placeholder",
            })

        return results[:30]
    @log_method
    def _research_fetch_and_extract(self, results: List[Dict[str, str]], external_access: bool) -> List[Dict[str, Any]]:
        extracts: List[Dict[str, Any]] = []
        for r in results:
            url = r.get("url", "")
            title = r.get("title", "")
            if not external_access or not url or url.startswith("MISSING_RESULT_"):
                extracts.append({
                    "url": url,
                    "title": title,
                    "text": "",
                    "date": None,
                    "content_type": "",
                    "skipped": True,
                    "error": "no_external_access_or_missing",
                })
                continue

            fetch = self._research_fetch_url(url)
            if fetch.get("error"):
                extracts.append({
                    "url": url,
                    "title": title,
                    "text": "",
                    "date": None,
                    "content_type": fetch.get("content_type", ""),
                    "skipped": True,
                    "error": fetch.get("error"),
                })
                continue

            content_type = fetch.get("content_type", "") or ""
            raw = fetch.get("content") or b""
            is_pdf = "application/pdf" in content_type.lower() or url.lower().endswith(".pdf")

            if is_pdf:
                text = _research_pdf_to_text_if_available(raw)
                if text is None:
                    extracts.append({
                        "url": url,
                        "title": title,
                        "text": "",
                        "date": None,
                        "content_type": content_type,
                        "skipped": True,
                        "error": "pdf_to_text_not_available",
                    })
                    continue
                date = _research_extract_date(text)
                extracts.append({
                    "url": url,
                    "title": title,
                    "text": text[:20000],
                    "date": date,
                    "content_type": content_type,
                    "skipped": False,
                    "error": None,
                })
                continue

            html_text = raw.decode(errors="ignore")
            page_title = _research_extract_title(html_text) or title
            text = _research_strip_html(html_text)
            date = _research_extract_date(html_text) or _research_extract_date(text)

            extracts.append({
                "url": url,
                "title": page_title,
                "text": text[:20000],
                "date": date,
                "content_type": content_type,
                "skipped": False,
                "error": None,
            })

        return extracts
    @log_method
    def _research_fetch_url(self, url: str) -> Dict[str, Any]:
        rate_limit = float(os.getenv("LLM_RESEARCH_RATE_LIMIT", "1.0"))
        max_retries = int(os.getenv("LLM_RESEARCH_FETCH_RETRIES", "2"))
        timeout = int(os.getenv("LLM_RESEARCH_FETCH_TIMEOUT", "15"))

        last_ts = getattr(self, "_research_last_fetch_ts", 0.0)
        err = None

        for attempt in range(max_retries + 1):
            wait = rate_limit - (time.time() - last_ts)
            if wait > 0:
                time.sleep(wait)

            try:
                req = Request(url, headers={"User-Agent": "MrRobotResearch/1.0"})
                with urlopen(req, timeout=timeout) as resp:
                    content = resp.read(2_000_000)
                    self._research_last_fetch_ts = time.time()
                    return {
                        "url": url,
                        "final_url": getattr(resp, "geturl", lambda: url)(),
                        "status_code": getattr(resp, "status", 200),
                        "content_type": resp.headers.get("content-type", ""),
                        "content": content,
                        "error": None,
                    }
            except Exception as e:
                err = str(e)
                self._log_research_event(
                    "FETCH_RETRY",
                    {"url": url, "attempt": attempt, "error": err},
                )
                time.sleep(2 ** attempt)
                last_ts = getattr(self, "_research_last_fetch_ts", 0.0)

        return {
            "url": url,
            "final_url": url,
            "status_code": 0,
            "content_type": "",
            "content": b"",
            "error": err or "fetch_failed",
        }
    @log_method
    def _research_rank_evidence(self, extracts: List[Dict[str, Any]], latest_bias: bool) -> List[Dict[str, Any]]:
        evidence: List[Dict[str, Any]] = []
        for ex in extracts:
            if ex.get("skipped"):
                continue
            url = ex.get("url", "")
            title = ex.get("title", "")
            text = ex.get("text", "")
            date = ex.get("date")
            claims = _research_split_claims(text, max_claims=3)
            rel = _research_compute_reliability_score(url, title)
            rec = _research_compute_recency_score(date)
            if latest_bias:
                score = (rec * 0.7) + (rel * 0.3)
            else:
                score = (rel * 0.6) + (rec * 0.4)
            evidence.append({
                "url": url,
                "title": title,
                "date": date,
                "key_claims": claims,
                "reliability_score": round(rel, 4),
                "domain": _research_extract_domain(url),
                "score": score,
            })

        evidence = sorted(
            evidence,
            key=lambda e: (e.get("score", 0.0), e.get("url", "")),
            reverse=True,
        )

        ranked = []
        for idx, ev in enumerate(evidence, start=1):
            ev = dict(ev)
            ev["id"] = idx
            ranked.append(ev)
        return ranked
    @log_method
    def _research_crosscheck(self, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        groups: List[Dict[str, Any]] = []
        for ev in evidence:
            domain = ev.get("domain", "")
            for claim in ev.get("key_claims", []) or []:
                tokens = set(_research_tokenize(claim))
                if not tokens:
                    continue
                matched = False
                for grp in groups:
                    if _research_jaccard(tokens, grp["tokens"]) >= 0.6:
                        grp["domains"].add(domain)
                        grp["source_ids"].add(ev.get("id"))
                        if len(claim) > len(grp["claim"]):
                            grp["claim"] = claim
                        matched = True
                        break
                if not matched:
                    groups.append({
                        "claim": claim,
                        "tokens": tokens,
                        "domains": {domain},
                        "source_ids": {ev.get("id")},
                    })

        verified = []
        unverified = []
        for grp in groups:
            item = {
                "claim": grp["claim"],
                "source_ids": sorted([i for i in grp["source_ids"] if i is not None]),
                "source_count": len(grp["domains"]),
            }
            if item["source_count"] >= 3:
                verified.append(item)
            else:
                unverified.append(item)

        return {"verified": verified, "unverified": unverified}
    @log_method
    def _research_format_context(
        self,
        *,
        user_text: str,
        layers: Dict[str, List[str]],
        results: List[Dict[str, str]],
        extracts: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        crosscheck: Dict[str, Any],
        latest_bias: bool,
        external_access: bool,
        dates_found: List[str],
    ) -> str:
        lines = []
        lines.append("Pre-response research context (auto-generated).")
        lines.append(f"Request date: {datetime.date.today().isoformat()}")
        lines.append(f"External access: {'enabled' if external_access else 'disabled'}")
        lines.append(f"Latest bias: {'on' if latest_bias else 'off'}")
        if _research_detect_missing_package_version(user_text):
            lines.append("Package version missing signal: detected (targeted registry queries enabled)")
        real_results = [
            r for r in results
            if r.get("url") and not str(r.get("url", "")).startswith("MISSING_RESULT_")
        ]
        if external_access and real_results:
            lines.append("")
            lines.append("Local web search results:")
            for r in real_results[:10]:
                title = str(r.get("title") or "").strip() or "(untitled)"
                url = str(r.get("url") or "").strip()
                snippet = str(r.get("snippet") or "").strip()
                lines.append(f"- {title}")
                if url:
                    lines.append(f"  {url}")
                if snippet:
                    lines.append(f"  {snippet}")
        lines.append("")
        lines.append("Query layers used:")
        lines.append("Layer A: " + "; ".join(layers.get("layer_a", [])))
        lines.append("Layer B: " + "; ".join(layers.get("layer_b", [])))
        lines.append("Layer C: " + "; ".join(layers.get("layer_c", [])))
        if layers.get("layer_git"):
            lines.append("Layer GIT: " + "; ".join(layers.get("layer_git", [])))
        lines.append("")
        lines.append(f"Results collected: {len(results)} (expected 30)")
        lines.append(f"Fetched/extracted: {len(extracts)} (top 10 processed)")
        if latest_bias and dates_found:
            lines.append("Dates found (latest first): " + ", ".join(dates_found))
        lines.append("")
        lines.append("Evidence table (ranked):")
        for ev in evidence:
            date_str = ev.get("date") or "UNKNOWN"
            # Sanitize claims from web content against prompt injection
            raw_claims = "; ".join(ev.get("key_claims", [])[:3])
            claims = _sanitize_external_content(raw_claims, label="evidence")
            title = _sanitize_external_content(str(ev.get("title", "")), label="title")
            lines.append(
                f"[{ev.get('id')}] {title} | {ev.get('url')} | {date_str} | "
                f"{ev.get('reliability_score')} | {claims}"
            )
        lines.append("")
        lines.append("Cross-check (>=3 independent sources):")
        verified = crosscheck.get("verified", [])
        if verified:
            for v in verified:
                lines.append(
                    f"- {v.get('claim')} (sources: {v.get('source_ids')})"
                )
        else:
            lines.append("- No claims verified across 3 independent sources.")
        lines.append("")
        lines.append("Instruction: Use inline citations like [n] referencing the evidence table above.")

        return "\n".join(lines)
    # --------------------------------------------------------------
    # 1️⃣  New helper method – detects “/planner” and runs the planner
    # --------------------------------------------------------------
    @log_method
    def _handle_planner_command(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """
        Scan the message list for a user message that starts with the
        literal command “/planner”. If found, invoke the global
        `run_planning_agent` function with the remainder of the line and
        return a JSON‑formatted plan.

        Returns:
            str – JSON string of the plan (ready for display) or
            None – no planner command present.
        """
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                content = msg["content"].strip()
                if content.lower().startswith("/planner"):
                    # Strip the command keyword and any leading whitespace
                    user_request = content[len("/planner"):].strip()
                    if not user_request:
                        # Empty request – return a minimal placeholder
                        return json.dumps(
                            {"error": "No request supplied after /planner"},
                            ensure_ascii=False,
                            indent=2,
                        )
                    # Call the existing planning routine (defined earlier in the file)
                    try:
                        plan_obj = run_planning_agent(user_request)
                    except Exception as exc:
                        return json.dumps(
                            {"error": f"Planner execution failed: {exc}"},
                            ensure_ascii=False,
                            indent=2,
                        )
                    # Convert the Pydantic model (or plain dict) to JSON for output
                    if hasattr(plan_obj, "dict"):
                        plan_dict = plan_obj.dict()
                    else:
                        plan_dict = plan_obj
                    return json.dumps(plan_dict, ensure_ascii=False, indent=2)
        return None
    # ------------------------------------------------------------------
    # Local tool support – schema + dispatch + agentic loop
    # ------------------------------------------------------------------

    def _build_local_tools_config(self, *, api: str = "chat") -> List[Dict[str, Any]]:
        """
        Build the ``tools`` list for the OpenAI API call.

        Args:
            api: ``"chat"`` for Chat Completions format or
                 ``"responses"`` for the Responses API format.

        When the backend supports the native ``web_search`` hosted tool
        *and* the user has it enabled, we include it alongside the
        local function-calling tools so the model can choose freely.
        """
        tools: List[Dict[str, Any]] = []

        # Always include our local tools (in the right format)
        tools.extend(get_all_tool_schemas(api=api))

        # Optionally include the OpenAI-hosted web_search tool too
        if self._web_search_enabled() and self._backend_supports_web_search_tool():
            tools.append({
                "type": "web_search",
                "external_web_access": bool(
                    getattr(self.config, "web_search_external_access", True)
                ),
            })

        return tools

    def _execute_tool_calls_from_response(self, resp: Any) -> List[Dict[str, Any]]:
        """
        Given a Responses-API response object, extract any function_call
        outputs, execute them locally, and return a list of tool-result
        dicts ready to feed back as ``input`` items.

        Every tool call is fully logged (args, result, timing) to both
        the research event logger and the daily JSONL logger.
        """
        tool_results: List[Dict[str, Any]] = []
        for item in getattr(resp, "output", []) or []:
            item_type = self._get(item, "type")
            if item_type != "function_call":
                continue

            call_id = self._get(item, "call_id") or self._get(item, "id") or ""
            fn_name = self._get(item, "name") or ""
            raw_args = self._get(item, "arguments") or "{}"

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}

            self._log_research_event(
                "TOOL_CALL_DISPATCH",
                {"tool": fn_name, "args": args, "call_id": call_id},
            )

            # ── Full tool call logging (args + result + timing) ──
            _tc_t0 = time.monotonic()
            result = dispatch_tool_call(fn_name, args)
            _tc_elapsed = round((time.monotonic() - _tc_t0) * 1000, 2)

            # Log full result (not just keys) to daily JSONL
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            safe_result = result_str[:500_000] + ("...[TRUNCATED]" if len(result_str) > 500_000 else "")
            try:
                self.llm_logger.info(json.dumps({
                    "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
                    "event": "tool_call_complete",
                    "api": "responses",
                    "tool": fn_name,
                    "call_id": call_id,
                    "args": args,
                    "elapsed_ms": _tc_elapsed,
                    "result_length": len(result_str),
                    "result": safe_result,
                }, ensure_ascii=False))
            except Exception:
                pass

            self._log_research_event(
                "TOOL_CALL_RESULT",
                {
                    "tool": fn_name,
                    "call_id": call_id,
                    "elapsed_ms": _tc_elapsed,
                    "result_keys": list(result.keys()) if isinstance(result, dict) else [],
                },
            )

            tool_results.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": result_str,
            })

        return tool_results

    def _execute_tool_calls_from_chat(self, message: Any) -> List[Dict[str, Any]]:
        """
        Given a Chat Completions message with tool_calls, execute them
        locally and return the assistant + tool messages to append.

        Every tool call is fully logged (args, result, timing) to both
        the research event logger and the daily JSONL logger.
        """
        follow_up: List[Dict[str, Any]] = []
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return follow_up

        # First, echo the assistant message with the tool_calls back
        tc_dicts = []
        for tc in tool_calls:
            tc_dicts.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            })
        follow_up.append({
            "role": "assistant",
            "tool_calls": tc_dicts,
        })

        # Then, execute each and add the results
        for tc in tool_calls:
            fn_name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}

            self._log_research_event(
                "TOOL_CALL_DISPATCH",
                {"tool": fn_name, "args": args, "call_id": tc.id},
            )

            # ── Full tool call logging (args + result + timing) ──
            _tc_t0 = time.monotonic()
            result = dispatch_tool_call(fn_name, args)
            _tc_elapsed = round((time.monotonic() - _tc_t0) * 1000, 2)

            # Log full result (not just keys) to daily JSONL
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            safe_result = result_str[:500_000] + ("...[TRUNCATED]" if len(result_str) > 500_000 else "")
            try:
                self.llm_logger.info(json.dumps({
                    "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
                    "event": "tool_call_complete",
                    "api": "chat.completions",
                    "tool": fn_name,
                    "call_id": tc.id,
                    "args": args,
                    "elapsed_ms": _tc_elapsed,
                    "result_length": len(result_str),
                    "result": safe_result,
                }, ensure_ascii=False))
            except Exception:
                pass

            self._log_research_event(
                "TOOL_CALL_RESULT",
                {
                    "tool": fn_name,
                    "call_id": tc.id,
                    "elapsed_ms": _tc_elapsed,
                    "result_keys": list(result.keys()) if isinstance(result, dict) else [],
                },
            )

            follow_up.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

        return follow_up

    def _prompt_provider(self) -> str:
        """Provider key for the prompt package (openai / xai)."""
        cfg = getattr(self, "config", None)
        explicit = getattr(cfg, "provider", None) if cfg is not None else None
        try:
            from src.llm.router import detect_provider

            model = None
            if hasattr(self, "_get_model_name"):
                try:
                    model = self._get_model_name()
                except Exception:
                    model = getattr(cfg, "model", None) if cfg is not None else None
            return detect_provider(model, explicit=explicit)
        except Exception:
            return "openai"

    def _get_search_query_prompt(self) -> str:
        return SEARCH_QUERY_PROMPT

    def _get_code_context_prompt(self) -> str:
        return CODE_CONTEXT_PROMPT

    def _build_secure_chat_messages(
        self,
        *,
        messages: List[Dict[str, str]],
        api_system_prompt: Optional[str],
        api_user_message: Optional[str],
        dark_recon_ctx: Optional[str],
    ) -> List[Dict[str, str]]:
        """Single source of truth for secure-chat message assembly.

        Always composes the **full security stack** via the multi-layer prompt
        engine (:func:`src.prompts.layers.build_secure_chat_messages`) with
        ``mode="multi"`` so every registered layer is sent as its own system
        message. Prompt package is selected by the central model/provider router.
        """
        provider = self._prompt_provider()
        try:
            from src.llm.router import get_router

            engine = get_router().get_prompt_engine(provider)
        except Exception:
            engine = None
        return build_secure_chat_messages(
            conversation_messages=messages,
            security_mode=True,
            api_system_prompt=api_system_prompt,
            api_user_message=api_user_message,
            dark_recon_ctx=dark_recon_ctx,
            mode="multi",
            engine=engine,
            provider=provider,
        )

    @log_method
    def secure_chat(
        self,
        messages: List[Dict[str, str]],
        resource_name: str = "resource",
        *,
        api_system_prompt: Optional[str] = None,
        api_user_message: Optional[str] = None,
    ) -> str:
        """
        secure_chat now supports two pass-through messages:
        - api_system_prompt: injected as a system message (highest risk if untrusted!)
        - api_user_message: injected as a user message (safer)
        """
        _chat_t0 = time.monotonic()   # wall-clock start for the entire chat

        if not self.config.enabled or self.client is None:
            audit_log("llm_chat_disabled", {"reason": "no_client"})
            return "LLM chat is disabled or unavailable."
        # -----------------------------------------------------------------
        # 2️⃣  Planner shortcut – if a user sent “/planner …”, short‑circuit
        # -----------------------------------------------------------------
        planner_result = self._handle_planner_command(messages)
        if planner_result is not None:
            # Return the planner output directly, skipping the normal LLM flow
            return planner_result
        # ---- daily file log: full request (messages + metadata) ----
        try:
            # Serialize full messages (cap each message at 50 KB for safety)
            safe_messages = []
            for m in (messages or []):
                sm = dict(m)
                c = sm.get("content", "")
                if isinstance(c, str) and len(c) > 50_000:
                    sm["content"] = c[:50_000] + "...[TRUNCATED]"
                safe_messages.append(sm)

            self.llm_logger.info(
                json.dumps(
                    {
                        "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
                        "event": "llm_request",
                        "layer": "secure_chat",
                        "resource": resource_name,
                        "model_config": self.config.model,
                        "model_resolved": self._get_model_name(),
                        "enabled": self.config.enabled,
                        "messages_count": len(messages or []),
                        "messages": safe_messages,
                        "has_api_system_prompt": bool(api_system_prompt),
                        "api_system_prompt": (api_system_prompt or "")[:10_000] if api_system_prompt else None,
                        "has_api_user_message": bool(api_user_message),
                        "api_user_message": (api_user_message or "")[:10_000] if api_user_message else None,
                        "temperature": self.config.temperature,
                        "top_p": self.config.top_p,
                        "max_tokens": self.config.max_tokens,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass


        # -----------------------------------------------------------------
        # 3️⃣  Sanitize any injected API messages (unchanged)
        # -----------------------------------------------------------------
        api_system_prompt = self._clean_inbound_text(api_system_prompt or "")
        api_user_message = self._clean_inbound_text((api_system_prompt or "") + (api_user_message or ""))

        # dark_recon context (optional layer input; always eligible on secure_chat)
        dark_recon_ctx = load_latest_dark_recon_summary(BASE_DIR / "data")

        # ---------------------------------------------------------------
        # secure_chat always uses the full security multi-layer stack.
        # Every registered prompt layer is composed and sent (no slim /
        # general path, no single-message merge).
        # ---------------------------------------------------------------
        self._log.info(
            "[secure_chat] query_mode=security layer_mode=multi messages=%d model=%s",
            len(messages or []),
            self._get_model_name(),
        )

        all_msgs = self._build_secure_chat_messages(
            messages=messages,
            api_system_prompt=api_system_prompt,
            api_user_message=api_user_message,
            dark_recon_ctx=dark_recon_ctx,
        )

        model_name = self._get_model_name()
        # Cap completion budget: huge values confuse providers / waste time
        max_out = max(1, min(int(self.config.max_tokens or 4096), 8192))
        sys_count = sum(1 for m in all_msgs if m.get("role") == "system")
        approx_chars = sum(len(str(m.get("content") or "")) for m in all_msgs)
        self._log.info(
            "[secure_chat] built messages | total=%d system=%d approx_chars=%d "
            "max_out=%d use_responses=%s",
            len(all_msgs),
            sys_count,
            approx_chars,
            max_out,
            self._should_use_responses_api(model_name),
        )

        if self._should_use_responses_api(model_name):
            instructions_parts: List[str] = []
            input_msgs: List[Dict[str, Any]] = []

            for m in all_msgs:
                role = m.get("role")
                content = m.get("content", "")
                if role == "system":
                    instructions_parts.append(content)
                    input_msgs.append(m)
                else:
                    input_msgs.append(m)

            instructions = "\n\n".join(instructions_parts).strip()

            # ── Build tools list (local + optional hosted) ──
            # local_tools = self._build_local_tools_config(api="responses")

            create_kwargs: Dict[str, Any] = {
                "model": model_name,
                "instructions": instructions,
                "input": input_msgs,
                "max_output_tokens": max_out,
                # "tools": local_tools,
                # "tool_choice": "auto",
            }

            # reasoning.summary is only supported by real OpenAI
            if self._backend_supports_reasoning():
                create_kwargs["reasoning"] = {
                    "effort": "high",
                    "summary": "auto",
                }

            if self._responses_supports_sampling(model_name):
                create_kwargs["temperature"] = self.config.temperature
                create_kwargs["top_p"] = self.config.top_p

            # ── Agentic tool-call loop (Responses API) ──
            self._log.info(
                "[secure_chat] calling responses.create | model=%s max_output_tokens=%d",
                model_name,
                max_out,
            )
            _llm_t0 = time.monotonic()
            resp = self.client.responses.create(**create_kwargs)
            _llm_elapsed = round((time.monotonic() - _llm_t0) * 1000, 2)
            self._log.info(
                "[secure_chat] responses.create done | elapsed_ms=%.2f",
                _llm_elapsed,
            )

            # Log the initial response (before any tool loop)
            self._log_llm_interaction(
                layer="secure_chat",
                api="responses",
                model=model_name,
                output_text=self._extract_responses_text(resp) or "",
                resp=resp,
                extra={"resource": resource_name, "stage": "initial"},
                elapsed_ms=_llm_elapsed,
            )

            # for _round in range(MAX_TOOL_CALL_ROUNDS):
            #     tool_outputs = self._execute_tool_calls_from_response(resp)
            #     if not tool_outputs:
            #         break  # no more tool calls – model is done

            #     self._log_research_event(
            #         "TOOL_LOOP_ROUND",
            #         {"round": _round + 1, "tool_calls": len(tool_outputs)},
            #     )

            #     # Feed results back and let the model continue
            #     follow_up_input = []
            #     # Include the full previous output so the model keeps context
            #     for item in getattr(resp, "output", []) or []:
            #         follow_up_input.append(item)
            #     # Add our tool results
            #     follow_up_input.extend(tool_outputs)

            #     # follow_up_kwargs: Dict[str, Any] = {
            #     #     "model": model_name,
            #     #     "instructions": instructions,
            #     #     "input": follow_up_input,
            #     #     "max_output_tokens": max_out,
            #     #     "tools": local_tools,
            #     #     "tool_choice": "auto",
            #     # }
            #     # previous_response_id is only supported by real OpenAI;
            #     # compatible backends (e.g. NVIDIA NIM) don't store
            #     # responses server-side and will 404.
            #     if self._is_openai_backend():
            #         follow_up_kwargs["previous_response_id"] = getattr(resp, "id", None)
            #     if self._backend_supports_reasoning():
            #         follow_up_kwargs["reasoning"] = {
            #             "effort": "high",
            #             "summary": "auto",
            #         }
            #     _round_t0 = time.monotonic()
            #     resp = self.client.responses.create(**follow_up_kwargs)
            #     _round_elapsed = round((time.monotonic() - _round_t0) * 1000, 2)

            #     # Log each tool-loop round response
            #     self._log_llm_interaction(
            #         layer="secure_chat",
            #         api="responses",
            #         model=model_name,
            #         output_text=self._extract_responses_text(resp) or "",
            #         resp=resp,
            #         extra={
            #             "resource": resource_name,
            #             "stage": "tool_loop",
            #             "round": _round + 1,
            #         },
            #         elapsed_ms=_round_elapsed,
            #     )

            content = self._extract_responses_text(resp) or ""
            _chat_total_ms = round((time.monotonic() - _chat_t0) * 1000, 2)

            # ── Final unified log (response + reasoning + thinking + tokens) ──
            self._log_llm_interaction(
                layer="secure_chat",
                api="responses",
                model=model_name,
                output_text=content,
                resp=resp,
                extra={
                    "resource": resource_name,
                    "stage": "final",
                    "total_chat_ms": _chat_total_ms,
                },
                elapsed_ms=_chat_total_ms,
            )

            normalized = self._normalize_code_blocks(content or "")
            return normalized.strip()

        # ── Build tools for Chat Completions (function type only) ──
        # chat_tools = [
        #     t for t in get_all_tool_schemas() if t.get("type") == "function"
        # ]

        chat_create_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": all_msgs,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": max_out,
            # "tools": chat_tools,
            # "tool_choice": "auto",
        }

        _backend = (
            getattr(self, "_api_base_url", None)
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("XAI_BASE_URL")
            or "default"
        )
        self._log.info(
            "[secure_chat] calling chat.completions.create | model=%s "
            "messages=%d max_tokens=%d backend=%s",
            model_name,
            len(all_msgs),
            max_out,
            str(_backend).strip(),
        )
        _llm_t0 = time.monotonic()
        response = self.client.chat.completions.create(**chat_create_kwargs)
        _llm_elapsed = round((time.monotonic() - _llm_t0) * 1000, 2)
        msg = response.choices[0].message
        self._log.info(
            "[secure_chat] chat.completions.create done | elapsed_ms=%.2f "
            "content_len=%d",
            _llm_elapsed,
            len(msg.content or ""),
        )

        # Log the initial response (before any tool loop)
        self._log_llm_interaction(
            layer="secure_chat",
            api="chat.completions",
            model=model_name,
            output_text=msg.content or "",
            response=response,
            extra={"resource": resource_name, "stage": "initial"},
            elapsed_ms=_llm_elapsed,
        )

        # ── Agentic tool-call loop (Chat Completions) ──
        for _round in range(MAX_TOOL_CALL_ROUNDS):
            follow_up = self._execute_tool_calls_from_chat(msg)
            if not follow_up:
                break  # no tool calls – model produced a final answer

            self._log_research_event(
                "TOOL_LOOP_ROUND_CHAT",
                {"round": _round + 1, "tool_calls": len([
                    f for f in follow_up if f.get("role") == "tool"
                ])},
            )

            # Extend the conversation with assistant + tool messages
            all_msgs.extend(follow_up)

            _round_t0 = time.monotonic()
            response = self.client.chat.completions.create(**{
                **chat_create_kwargs,
                "messages": all_msgs,
            })
            _round_elapsed = round((time.monotonic() - _round_t0) * 1000, 2)
            msg = response.choices[0].message

            # Log each tool-loop round response
            self._log_llm_interaction(
                layer="secure_chat",
                api="chat.completions",
                model=model_name,
                output_text=msg.content or "",
                response=response,
                extra={
                    "resource": resource_name,
                    "stage": "tool_loop",
                    "round": _round + 1,
                },
                elapsed_ms=_round_elapsed,
            )

        content = msg.content or ""
        _chat_total_ms = round((time.monotonic() - _chat_t0) * 1000, 2)

        # ── Final unified log (response + reasoning + thinking + tokens) ──
        self._log_llm_interaction(
            layer="secure_chat",
            api="chat.completions",
            model=model_name,
            output_text=content,
            response=response,
            extra={
                "resource": resource_name,
                "stage": "final",
                "total_chat_ms": _chat_total_ms,
            },
            elapsed_ms=_chat_total_ms,
        )

        normalized = self._normalize_code_blocks(content or "")
        return normalized.strip()
    @log_method
    def create_thread(
        self,
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Any:
        if not self.config.enabled or self.client is None:
            raise RuntimeError("LLM client not initialized; cannot create thread.")

        payload_messages: List[Dict[str, Any]] = []
        allowed_roles = {"user", "assistant","system"}

        for msg in messages or []:
            role = str(msg.get("role", "")).strip().lower()
            if role not in allowed_roles:
                raise ValueError(f"Unsupported message role '{role}' for Assistants threads.")
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            payload_messages.append({"role": role, "content": content})

        create_kwargs: Dict[str, Any] = {}
        if payload_messages:
            create_kwargs["messages"] = payload_messages
        if metadata:
            create_kwargs["metadata"] = metadata

        thread = self.client.beta.threads.create(**create_kwargs)

        audit_log(
            "llm_thread_created",
            {
                "messages_included": len(payload_messages),
                "metadata_keys": list(metadata.keys()) if metadata else [],
                "assistant_id": self.config.assistant_id,
            },
        )

        return thread
    @log_method
    def _should_use_responses_api(self, model_name: str) -> bool:
        # Prefer Responses if you want reasoning summaries or tool support.
        if getattr(self.config, "always_use_responses_api", False):
            return True
        if self._web_search_enabled():
            return True
        return model_name.startswith("gpt-5")

    def _get(self,obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    
    def _extract_responses_text(self, resp: Any) -> str:
            text = getattr(resp, "output_text", None)
            if text:
                return str(text)


            chunks: List[str] = []
            for item in self._get(resp, "output", []) or []:
                if self._get(item, "type") != "message":
                    continue
                for c in self._get(item, "content", []) or []:
                    if self._get(c, "type") in ("output_text", "text"):
                        t = self._get(c, "text")
                        if t:
                            chunks.append(str(t))
            return "".join(chunks)

    @log_method
    def stream_print_unified(self, stream: Iterator[Any]) -> None:
        """
        Unified streamer for:
        - OpenAI Responses API streaming (SSE event objects with .type like 'response.output_text.delta')
        - OpenAI-compatible Chat Completions streaming (incl. NVIDIA NIM) chunks with choices[0].delta.content

        Prints text as it arrives. Also prints reasoning *summaries* if the stream provides them.
        Accumulates all content and reasoning for a final log entry.
        """
        # Accumulators for post-stream logging
        _text_parts: List[str] = []
        _reasoning_parts: List[str] = []
        _stream_api = "unknown"

        for ev in stream:
            ev_type = self._get(ev, "type", None)

            # --- OpenAI Responses API streaming events ---
            if isinstance(ev_type, str) and ev_type.startswith("response."):
                _stream_api = "responses"
                if ev_type == "response.output_text.delta":
                    delta = self._get(ev, "delta", "")
                    if delta:
                        print(delta, end="", flush=True)
                        _text_parts.append(delta)

                elif ev_type == "response.reasoning_summary_text.delta":
                    # This is the *reasoning summary* channel (not raw chain-of-thought).
                    delta = self._get(ev, "delta", "")
                    if delta:
                        # choose your own prefix/sink; printing inline here
                        print(delta, end="", flush=True)
                        _reasoning_parts.append(delta)

                # Optional: handle refusal deltas if you want
                # elif ev_type == "response.refusal.delta":
                #     delta = _get(ev, "delta", "")
                #     if delta:
                #         print(delta, end="", flush=True)

                continue

            # --- OpenAI-compatible Chat Completions streaming (NVIDIA NIM, many others) ---
            # Expected shape: chunk.choices[0].delta.content
            choices = self._get(ev, "choices", None)
            if choices and len(choices) > 0:
                _stream_api = "chat.completions"
                delta_obj = self._get(choices[0], "delta", None)
                if delta_obj is not None:
                    content = self._get(delta_obj, "content", None)
                    if content:
                        print(content, end="", flush=True)
                        _text_parts.append(content)

                    # Some vendors add nonstandard reasoning fields; safe optional read:
                    rc = self._get(delta_obj, "reasoning_content", None)
                    if rc:
                        print(rc, end="", flush=True)
                        _reasoning_parts.append(rc)

                continue

            # If we get here, it's an unrecognized chunk type. Ignore silently or log:
            # print(f"\n[debug] unknown chunk: {ev!r}\n")
            continue

        # ── Post-stream: log accumulated content + reasoning ──
        try:
            full_text = "".join(_text_parts)
            full_reasoning = "".join(_reasoning_parts)
            model_name = self._get_model_name()
            base_url = os.getenv("OPENAI_BASE_URL", "").strip()
            ts = datetime.datetime.now().isoformat(timespec="seconds")

            safe_text = self._clean_inbound_text(full_text, max_len=10_000) or ""
            self.llm_logger.info(json.dumps({
                "ts": ts,
                "event": "llm_response",
                "layer": "stream",
                "api": _stream_api,
                "model": model_name,
                "backend": base_url or "default",
                "text": safe_text,
                "streamed_chars": len(full_text),
            }, ensure_ascii=False))

            safe_reasoning = self._clean_inbound_text(full_reasoning, max_len=10_000_000) or ""
            self.llm_logger.info(json.dumps({
                "ts": ts,
                "event": "llm_reasoning",
                "layer": "stream",
                "api": _stream_api,
                "model": model_name,
                "backend": base_url or "default",
                "missing": not bool(safe_reasoning),
                "reasoning": safe_reasoning,
            }, ensure_ascii=False))

            # Thinking section (embedded in streamed text)
            thinking = ""
            if hasattr(self, "_extract_section"):
                thinking = self._extract_section(full_text or "", "Thinking")
            self.llm_logger.info(json.dumps({
                "ts": ts,
                "event": "llm_thinking",
                "layer": "stream",
                "api": _stream_api,
                "model": model_name,
                "backend": base_url or "default",
                "missing": not bool(thinking),
                "thinking": thinking if thinking else None,
            }, ensure_ascii=False))
        except Exception:
            pass

    @log_method
    def extract_reasoning_summary_from_response(self, resp: Any) -> str:
        """
        For non-streamed OpenAI Responses API objects:
        - Prefer item.summary[*].type == 'summary_text'
        - Fallback to item.content[*].type == 'reasoning_text' (what your sample shows)
        """
        chunks: list[str] = []
        out = self._get(resp, "output", []) or []

        for item in out:
            if self._get(item, "type") != "reasoning":
                continue

            # 1) Preferred: structured summary (when present)
            summ = self._get(item, "summary", None)
            if isinstance(summ, dict):
                summ = [summ]
            if summ:
                for s in summ:
                    if self._get(s, "type") == "summary_text":
                        t = self._get(s, "text", None)
                        if t:
                            chunks.append(str(t))

            # 2) Fallback: reasoning_text inside content (your case)
            content = self._get(item, "content", None)
            if isinstance(content, dict):
                content = [content]
            if content:
                for c in content:
                    ctype = self._get(c, "type")
                    if ctype in ("reasoning_text", "summary_text"):
                        t = self._get(c, "text", None)
                        if t:
                            chunks.append(str(t))

            # 3) Extra fallback if SDK exposes a direct text field
            t2 = self._get(item, "text", None)
            if t2:
                chunks.append(str(t2))

        # de-dupe while preserving order
        seen = set()
        uniq: list[str] = []
        for c in chunks:
            c = c.strip()
            if c and c not in seen:
                uniq.append(c)
                seen.add(c)

        return "\n".join(uniq).strip()

    def _extract_chat_reasoning(self, response: Any) -> str:
        try:
            msg = response.choices[0].message
            r = getattr(msg, "reasoning", None)
            return str(r).strip() if r else ""
        except Exception:
            return ""
