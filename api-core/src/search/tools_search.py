"""
Web‑search wrapper used by the planning agent.

Primary implementation uses **ddgr** (DuckDuckGo CLI).  
If ddgr is missing or blocked, we fall back to a lightweight HTML scrape of DuckDuckGo.
"""

from __future__ import annotations
import json
import os
import subprocess
import shutil
import urllib.parse
import urllib.request
import re
from typing import List, Dict, Any
from html.parser import HTMLParser
import datetime
# ----------------------------------------------------------------------
# Helper HTML parser (strip tags)
# ----------------------------------------------------------------------
class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._data: List[str] = []

    def handle_data(self, d: str) -> None:
        self._data.append(d)

    def get_text(self) -> str:
        return " ".join(self._data).strip()


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


# ----------------------------------------------------------------------
# Low‑level command runner
# ----------------------------------------------------------------------
def _run_cmd(cmd: List[str], *, timeout: int = 20, env: Dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"Command failed: {' '.join(cmd)}")
    return proc.stdout.strip()


# ----------------------------------------------------------------------
# HTML fallback (no ddgr)
# ----------------------------------------------------------------------
def _ddg_html_search(query: str, *, max_results: int = 5) -> List[Dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=data,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode(errors="ignore")

    # Very simple extraction – title + url + snippet
    link_re = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    snippet_re = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.I | re.S)

    links = link_re.findall(html)
    snippets = snippet_re.findall(html)

    results = []
    for idx, (url, title_html) in enumerate(links):
        title = _strip_html(title_html)
        snippet = _strip_html(snippets[idx]) if idx < len(snippets) else ""
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": "duckduckgo-html",
                "published_date": None,
            }
        )
        if len(results) >= max_results:
            break
    return results


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def search_web(query: str, *, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Perform a web search and return a list of dicts:
    {
        "title": str,
        "snippet": str,
        "url": str,
        "source": str,               # e.g. "ddgr" or "duckduckgo-html"
        "published_date": str|None,
    }
    """
    query = query.strip()
    if not query:
        return []

    # Try ddgr first
    try:
        out = _run_cmd(["ddgr", "-n", str(max_results), "--json", query])
        data = json.loads(out) if out else []
        results = [
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "snippet": str(item.get("abstract", "")) or str(item.get("snippet", "")),
                "source": "ddgr",
                "published_date": None,
            }
            for item in data[:max_results]
        ]
        if results:
            return results
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
        # ddgr missing or failed – fall back
        pass

    # HTML fallback
    return _ddg_html_search(query, max_results=max_results)


def normalize_results(query_id: str, query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert raw search results into the unified EvidenceItem shape.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    normalized = []
    for i, r in enumerate(results):
        normalized.append(
            {
                "id": f"{query_id}.{i+1}",
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "source": r.get("source", ""),
                "url": r.get("url", ""),
                "published_date": r.get("published_date"),
                "retrieved_date": now,
                "notes": f"Query: {query}",
            }
        )
    return normalized