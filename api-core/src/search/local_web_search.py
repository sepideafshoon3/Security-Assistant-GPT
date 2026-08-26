# src/search/local_web_search.py
from __future__ import annotations
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class WebResult:
    title: str
    url: str
    snippet: str = ""

def _run(cmd: list[str], *, timeout: int = 20, env: Optional[Dict[str, str]] = None) -> tuple[str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f"command failed: {' '.join(cmd)}")
    return p.stdout, p.stderr


def _use_tor_for_search() -> bool:
    return os.getenv("LLM_WEB_SEARCH_USE_TOR", "").strip().lower() in ("1", "true", "yes", "on")


def _tor_proxy_url() -> str:
    return os.getenv("LLM_TOR_SOCKS", "").strip() or "socks5h://127.0.0.1:9050"

def _sanitize_query(q: str) -> str:
    q = (q or "").strip()
    q = re.sub(r"\s+", " ", q)
    if len(q) > 200:
        q = q[:200]
    return q


def _user_agent() -> str:
    # Keep it simple to avoid triggering anti-bot blocks.
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _strip_tags(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def _ddg_html_search(query: str, *, max_results: int = 5) -> List[WebResult]:
    """
    Fallback search using DuckDuckGo's HTML endpoint (POST).
    This avoids ddgr's occasional 202/403 responses in locked-down environments.
    """
    query = _sanitize_query(query)
    if not query:
        return []

    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=data,
        headers={
            "User-Agent": _user_agent(),
            "Accept": "text/html",
        },
    )

    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    link_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    snippet_re = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    links = link_re.findall(html)
    snippets = snippet_re.findall(html)

    results: List[WebResult] = []
    for idx, (url, title_html) in enumerate(links):
        title = html_lib.unescape(_strip_tags(title_html)).strip()
        snippet = ""
        if idx < len(snippets):
            snippet = html_lib.unescape(_strip_tags(snippets[idx])).strip()

        url = html_lib.unescape(url).strip()
        if "duckduckgo.com/l/?" in url and "uddg=" in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("uddg"):
                url = urllib.parse.unquote(qs["uddg"][0])

        if not url:
            continue

        results.append(WebResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break

    return results


def _is_ddgr_block_error(msg: str) -> bool:
    if not msg:
        return False
    msg = msg.lower()
    # DuckDuckGo occasionally returns non-200 responses to CLI clients.
    return any(code in msg for code in ("http error 202", "http error 403", "http error 429", "http error 503"))

def web_search(query: str, *, max_results: int = 5) -> List[WebResult]:
    """
    Local web search using a CLI tool.
    Recommended: ddgr (DuckDuckGo CLI). Requires install on server.
    Optional: set LLM_WEB_SEARCH_USE_TOR=1 to route via Tor (SOCKS5 at 127.0.0.1:9050).
    """
    query = _sanitize_query(query)
    if not query:
        return []

    # ddgr JSON output
    # ddgr -n 5 --json "query"
    cmd = ["ddgr", "-n", str(max_results), "--json", query]
    env = None
    if _use_tor_for_search():
        tor_proxy = _tor_proxy_url()
        env = dict(os.environ)
        env.setdefault("ALL_PROXY", tor_proxy)
        env.setdefault("HTTPS_PROXY", tor_proxy)
        env.setdefault("HTTP_PROXY", tor_proxy)
        if shutil.which("torsocks"):
            cmd = ["torsocks"] + cmd

    try:
        out, err = _run(cmd, timeout=25, env=env)
        if err.strip() and (not out.strip() or out.strip() == "[]"):
            if _is_ddgr_block_error(err):
                return _ddg_html_search(query, max_results=max_results)
            raise RuntimeError(err.strip())

        data = json.loads(out) if out.strip() else []
        results: List[WebResult] = []
        for item in data[:max_results]:
            title = str(item.get("title", "")) or ""
            url = str(item.get("url", "")) or ""
            snippet = str(item.get("abstract", "")) or str(item.get("snippet", "")) or ""
            if not url.strip():
                continue
            results.append(WebResult(
                title=title,
                url=url,
                snippet=snippet,
            ))
        if results:
            return results
        # ddgr sometimes returns empty results with no error; fall back to HTML
        return _ddg_html_search(query, max_results=max_results)
    except (FileNotFoundError, subprocess.TimeoutExpired, HTTPError, URLError, RuntimeError):
        # ddgr missing, blocked, or timed out; attempt HTML fallback
        return _ddg_html_search(query, max_results=max_results)
