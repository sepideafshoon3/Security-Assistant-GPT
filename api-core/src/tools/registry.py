# src/tools/registry.py
"""
Unified local-tool registry.

Every tool the LLM can invoke is declared here with its OpenAI
function-calling schema and a Python dispatcher.  The LLM sees the
schema via ``get_all_tool_schemas()``; the execution loop calls
``dispatch_tool_call(name, arguments)`` to run the right function
and return a JSON-serialisable result.

Adding a new tool:
    1. Write a ``_handle_<name>(args)`` function below.
    2. Add its schema to ``TOOL_SCHEMAS``.
    3. Register name -> handler in ``_DISPATCH``.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import time as _time
import threading as _threading

from src.search.local_web_search import web_search, WebResult
from src.search.tools_search import search_web as tools_search_web, normalize_results
from src.search.exploitdb_client import ExploitDBClient
from src.search.searchsploit_client import SearchsploitClient

logger = logging.getLogger(__name__)


# ======================================================================
# Daily JSONL logger for structured tool events
# ======================================================================
def _get_tool_jsonl_logger() -> logging.Logger:
    """Lazy-init a daily JSONL logger for tool call events.

    Writes to the same ``logs/llm/`` directory as the LLM logger so that
    tool calls and LLM responses can be correlated in a single log stream.
    """
    try:
        from src.core.paths import BASE_DIR as _BASE_DIR
        log_dir_env = os.getenv("LLM_LOG_DIR")
        log_dir = Path(log_dir_env).expanduser() if log_dir_env else (_BASE_DIR / "logs" / "llm")
        log_dir.mkdir(parents=True, exist_ok=True)

        _logger = logging.getLogger("mrrobot.tools")
        if not any(getattr(h, "log_dir", None) == log_dir for h in _logger.handlers):
            from src.llm.openai_client import DailyFileHandler
            h = DailyFileHandler(log_dir=log_dir, prefix="tools")
            h.setFormatter(logging.Formatter("%(message)s"))
            _logger.addHandler(h)
            _logger.setLevel(logging.INFO)
            _logger.propagate = False
        return _logger
    except Exception:
        return logging.getLogger("mrrobot.tools")


def _safe_serialize(obj: Any, max_len: int = 1_000_000) -> str:
    """JSON-serialize *obj* with a safety cap to avoid giant log lines."""
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        text = repr(obj)
    if len(text) > max_len:
        return text[:max_len] + "...[TRUNCATED]"
    return text

# ======================================================================
# Rate-limiter for search tools (prevents DDG blocks during tool loops)
# ======================================================================
_search_rate_lock = _threading.Lock()
_search_last_call: float = 0.0
_SEARCH_MIN_INTERVAL = 3.0  # seconds between search calls

# ======================================================================
# Tool schemas (OpenAI function-calling format)
# ======================================================================

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------
    # 1) Web Search (DuckDuckGo via ddgr / HTML fallback)
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet using DuckDuckGo. Returns titles, URLs, "
                "and snippets. Use for any query that needs current or external "
                "information: CVEs, latest tools, documentation, news, research, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1-20). Default 10.",
                        "default": 10,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    # ------------------------------------------------------------------
    # 2) ExploitDB search
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "exploitdb_search",
            "description": (
                "Search ExploitDB for known exploits by keyword. Returns metadata "
                "only (ID, title, platform, type, URL). Use when the user asks about "
                "known exploits, CVE PoCs, or vulnerability databases."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search in ExploitDB (e.g. 'Apache 2.4.49').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return. Default 5.",
                        "default": 5,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    # ------------------------------------------------------------------
    # 3) SearchSploit (local exploitdb mirror)
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "searchsploit",
            "description": (
                "Search the local ExploitDB mirror using the searchsploit CLI. "
                "Returns exploit metadata (EDB-ID, title, platform, type, path). "
                "Useful for offline exploit lookup when searchsploit is installed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term (e.g. 'WordPress 5.8').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 5.",
                        "default": 5,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    # ------------------------------------------------------------------
    # 4) Semgrep static analysis
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "run_semgrep",
            "description": (
                "Run Semgrep static analysis on a repository or directory. "
                "Returns JSON findings of security issues, bugs, and code-smell. "
                "Use when the user asks to scan code for vulnerabilities."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_path": {
                        "type": "string",
                        "description": "Absolute path to the repository or directory to scan.",
                    },
                },
                "required": ["repository_path"],
                "additionalProperties": False,
            },
        },
    },
    # ------------------------------------------------------------------
    # 5) Bandit (Python security linter)
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "run_bandit",
            "description": (
                "Run Bandit security linter on a Python codebase. "
                "Returns JSON findings of common Python security issues. "
                "Use when the user asks to check Python code for vulnerabilities."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_path": {
                        "type": "string",
                        "description": "Absolute path to the Python repository or directory to scan.",
                    },
                },
                "required": ["repository_path"],
                "additionalProperties": False,
            },
        },
    },
    # ------------------------------------------------------------------
    # 6) OSV Scanner (vulnerability database)
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "run_osv_scanner",
            "description": (
                "Run OSV-Scanner to check project dependencies against the "
                "Open Source Vulnerabilities database. Returns known CVEs "
                "affecting the project's dependencies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repository_path": {
                        "type": "string",
                        "description": "Absolute path to the repository to scan for vulnerable dependencies.",
                    },
                },
                "required": ["repository_path"],
                "additionalProperties": False,
            },
        },
    },
    # ------------------------------------------------------------------
    # 7) Multi-query research (batch web search + dedup)
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "research_search",
            "description": (
                "Run multiple web searches in batch, deduplicate results, and "
                "return a unified evidence list. Use for deep research that needs "
                "several related queries (e.g. CVE details + PoC + patches)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of search query strings to execute.",
                    },
                    "max_results_per_query": {
                        "type": "integer",
                        "description": "Max results per individual query. Default 5.",
                        "default": 5,
                    },
                },
                "required": ["queries"],
                "additionalProperties": False,
            },
        },
    },
]


# ======================================================================
# Tool handlers
# ======================================================================

def _rate_limited_search(query: str, max_results: int = 10) -> List[WebResult]:
    """Execute web_search with rate limiting to avoid DDG blocks."""
    global _search_last_call
    with _search_rate_lock:
        elapsed = _time.time() - _search_last_call
        if elapsed < _SEARCH_MIN_INTERVAL:
            wait = _SEARCH_MIN_INTERVAL - elapsed
            logger.info("Rate-limiting search: waiting %.1fs", wait)
            _time.sleep(wait)
        _search_last_call = _time.time()

    return web_search(query, max_results=max_results)


def _handle_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query", "")).strip()
    max_results = int(args.get("max_results", 10))
    if not query:
        return {"error": "Empty query", "results": []}

    try:
        results: List[WebResult] = _rate_limited_search(query, max_results)
        if not results:
            return {
                "query": query,
                "results": [],
                "note": (
                    "Search returned no results. This may be due to rate limiting "
                    "by the search provider. The pre-response research context "
                    "above likely already contains relevant results for this query. "
                    "Use those results instead of searching again."
                ),
            }
        return {
            "query": query,
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in results
            ],
        }
    except Exception as e:
        logger.warning("web_search tool failed: %r", e)
        return {
            "error": str(e),
            "results": [],
            "note": (
                "Search failed. The pre-response research context above "
                "likely already contains relevant results. Use those instead."
            ),
        }


def _handle_exploitdb_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 5))
    if not query:
        return {"error": "Empty query", "results": []}

    try:
        client = ExploitDBClient()
        results = client.search(query, limit=limit)
        return {
            "query": query,
            "results": [
                {
                    "id": r.id,
                    "title": r.title,
                    "platform": r.platform,
                    "type": r.type,
                    "url": r.url,
                }
                for r in results
            ],
        }
    except Exception as e:
        logger.warning("exploitdb_search tool failed: %r", e)
        return {"error": str(e), "results": []}


def _handle_searchsploit(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 5))
    if not query:
        return {"error": "Empty query", "results": []}

    try:
        client = SearchsploitClient()
        results = client.search(query, limit=limit)
        return {
            "query": query,
            "results": [
                {
                    "edb_id": r.edb_id,
                    "title": r.title,
                    "platform": r.platform,
                    "exploit_type": r.exploit_type,
                    "path": r.path,
                }
                for r in results
            ],
        }
    except Exception as e:
        logger.warning("searchsploit tool failed: %r", e)
        return {"error": str(e), "results": []}


def _handle_run_semgrep(args: Dict[str, Any]) -> Dict[str, Any]:
    from src.tools.semgrep_runner import run_semgrep
    from src.core.paths import BASE_DIR

    repo_path = str(args.get("repository_path", "")).strip()
    if not repo_path:
        return {"error": "repository_path is required"}

    reports_dir = BASE_DIR / "reports"
    result = run_semgrep(repo_path, reports_dir)
    output: Dict[str, Any] = {
        "action": result.action,
        "success": result.success,
    }
    if result.output_path and os.path.exists(result.output_path):
        try:
            with open(result.output_path, "r") as f:
                data = json.load(f)
            # Return a summary rather than the full giant JSON
            findings = data.get("results", [])
            output["findings_count"] = len(findings)
            output["findings_preview"] = findings[:10]
        except Exception:
            output["output_path"] = result.output_path
    if result.errors:
        output["errors"] = result.errors
    return output


def _handle_run_bandit(args: Dict[str, Any]) -> Dict[str, Any]:
    from src.tools.bandit_runner import run_bandit
    from src.core.paths import BASE_DIR

    repo_path = str(args.get("repository_path", "")).strip()
    if not repo_path:
        return {"error": "repository_path is required"}

    reports_dir = BASE_DIR / "reports"
    result = run_bandit(repo_path, reports_dir)
    output: Dict[str, Any] = {
        "action": result.action,
        "success": result.success,
    }
    if result.output_path and os.path.exists(result.output_path):
        try:
            with open(result.output_path, "r") as f:
                data = json.load(f)
            findings = data.get("results", [])
            output["findings_count"] = len(findings)
            output["findings_preview"] = findings[:10]
        except Exception:
            output["output_path"] = result.output_path
    if result.errors:
        output["errors"] = result.errors
    return output


def _handle_run_osv_scanner(args: Dict[str, Any]) -> Dict[str, Any]:
    from src.tools.osv_runner import run_osv_scanner
    from src.core.paths import BASE_DIR

    repo_path = str(args.get("repository_path", "")).strip()
    if not repo_path:
        return {"error": "repository_path is required"}

    reports_dir = BASE_DIR / "reports"
    result = run_osv_scanner(repo_path, reports_dir)
    output: Dict[str, Any] = {
        "action": result.action,
        "success": result.success,
    }
    if result.output_path and os.path.exists(result.output_path):
        try:
            with open(result.output_path, "r") as f:
                data = json.load(f)
            output["scan_result"] = data
        except Exception:
            output["output_path"] = result.output_path
    if result.errors:
        output["errors"] = result.errors
    return output


def _handle_research_search(args: Dict[str, Any]) -> Dict[str, Any]:
    queries = args.get("queries", [])
    max_per = int(args.get("max_results_per_query", 5))
    if not queries:
        return {"error": "No queries provided", "results": []}

    all_results: List[Dict[str, Any]] = []
    seen_urls: set = set()
    errors: List[str] = []

    for idx, q in enumerate(queries):
        q = str(q).strip()
        if not q:
            continue
        try:
            batch = _rate_limited_search(q, max_per)
            for r in batch:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                all_results.append({
                    "query": q,
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                })
        except Exception as e:
            logger.warning("research_search query '%s' failed: %r", q, e)
            errors.append(f"Query '{q}': {e}")

    result: Dict[str, Any] = {
        "queries_executed": len(queries),
        "total_results": len(all_results),
        "results": all_results,
    }
    if not all_results:
        result["note"] = (
            "All searches returned empty results, likely due to rate limiting. "
            "The pre-response research context above already contains relevant "
            "results. Use those instead of searching again."
        )
    if errors:
        result["errors"] = errors
    return result


# ======================================================================
# Dispatch table
# ======================================================================

_DISPATCH: Dict[str, Any] = {
    "web_search": _handle_web_search,
    "exploitdb_search": _handle_exploitdb_search,
    "searchsploit": _handle_searchsploit,
    "run_semgrep": _handle_run_semgrep,
    "run_bandit": _handle_run_bandit,
    "run_osv_scanner": _handle_run_osv_scanner,
    "research_search": _handle_research_search,
}


# ======================================================================
# Public API
# ======================================================================

def get_all_tool_schemas(*, api: str = "chat") -> List[Dict[str, Any]]:
    """Return all tool schemas for passing to the OpenAI API.

    Args:
        api: ``"chat"`` for Chat Completions format (nested ``function`` key)
             or ``"responses"`` for the Responses API format (flat, top-level
             ``name`` / ``parameters``).
    """
    if api == "responses":
        return _to_responses_format(TOOL_SCHEMAS)
    return list(TOOL_SCHEMAS)


def _to_responses_format(schemas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Chat Completions tool schemas to Responses API format.

    Chat Completions:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

    Responses API:
        {"type": "function", "name": ..., "description": ..., "parameters": ...}
    """
    out: List[Dict[str, Any]] = []
    for s in schemas:
        if s.get("type") == "function" and "function" in s:
            fn = s["function"]
            flat: Dict[str, Any] = {"type": "function"}
            flat["name"] = fn.get("name", "")
            flat["description"] = fn.get("description", "")
            if "parameters" in fn:
                flat["parameters"] = fn["parameters"]
            if "strict" in fn:
                flat["strict"] = fn["strict"]
            out.append(flat)
        else:
            # Non-function tools (e.g. web_search hosted) pass through as-is
            out.append(dict(s))
    return out


def get_tool_names() -> List[str]:
    """Return the names of all registered tools."""
    return list(_DISPATCH.keys())


def dispatch_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a tool by name with the given arguments.
    Returns a JSON-serialisable dict with the tool output.

    Every call is fully logged to both the standard logger and the
    daily JSONL file (``logs/llm/tools-YYYY-MM-DD.log``) with:
      - full arguments
      - full result
      - execution wall-time
      - error / traceback on failure
    """
    ts_start = datetime.datetime.now()
    t0 = _time.monotonic()
    tool_log = _get_tool_jsonl_logger()

    handler = _DISPATCH.get(name)
    if handler is None:
        logger.error("Unknown tool requested: %s", name)
        _emit_tool_event(tool_log, "tool_call_error", name, arguments,
                         error=f"Unknown tool: {name}",
                         ts_start=ts_start, elapsed_ms=0)
        return {"error": f"Unknown tool: {name}"}

    # ── Log start ──
    logger.info("Tool call START: %s | args=%s", name, _safe_serialize(arguments, 2000))
    _emit_tool_event(tool_log, "tool_call_start", name, arguments,
                     ts_start=ts_start, elapsed_ms=0)

    try:
        result = handler(arguments)
        elapsed_ms = round((_time.monotonic() - t0) * 1000, 2)

        logger.info("Tool call END:   %s | %dms | result_keys=%s",
                     name, elapsed_ms,
                     list(result.keys()) if isinstance(result, dict) else type(result).__name__)

        # ── Log full result ──
        _emit_tool_event(tool_log, "tool_call_end", name, arguments,
                         result=result, ts_start=ts_start, elapsed_ms=elapsed_ms)
        return result

    except Exception as e:
        elapsed_ms = round((_time.monotonic() - t0) * 1000, 2)
        tb = traceback.format_exc()
        logger.error("Tool call FAIL:  %s | %dms | error=%r", name, elapsed_ms, e)

        _emit_tool_event(tool_log, "tool_call_error", name, arguments,
                         error=str(e), traceback_str=tb,
                         ts_start=ts_start, elapsed_ms=elapsed_ms)
        return {"error": f"Tool {name} failed: {e}"}


def _emit_tool_event(
    tool_log: logging.Logger,
    event: str,
    name: str,
    arguments: Dict[str, Any],
    *,
    result: Any = None,
    error: Optional[str] = None,
    traceback_str: Optional[str] = None,
    ts_start: Optional[datetime.datetime] = None,
    elapsed_ms: float = 0,
) -> None:
    """Write a structured JSONL line for a tool event."""
    try:
        entry: Dict[str, Any] = {
            "ts": (ts_start or datetime.datetime.now()).isoformat(timespec="milliseconds"),
            "event": event,
            "tool": name,
            "args": arguments,
            "elapsed_ms": elapsed_ms,
        }
        if result is not None:
            entry["result"] = _safe_serialize(result)
        if error is not None:
            entry["error"] = error
        if traceback_str:
            entry["traceback"] = traceback_str[:5000]
        tool_log.info(json.dumps(entry, ensure_ascii=False, default=str))
    except Exception:
        pass  # never crash the app because of logging
