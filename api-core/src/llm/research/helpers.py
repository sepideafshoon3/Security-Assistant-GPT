"""Stateless research helpers extracted from ``openai_client.py``.

Query expansion, URL/date/title extraction, recency and reliability
scoring, and HTML/PDF-to-text. Leaf module: it must not import from
``src.llm.openai_client``.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.llm.research.constants import (
    _GIT_REPO_HINTS,
    _PLANNER_TARGETS,
    _REDTEAM_HINTS,
    _RESEARCH_PACKAGE_REGISTRIES,
    _RESEARCH_STOPWORDS,
    _RESEARCH_SYNONYMS,
)
from src.llm.sanitize import _sanitize_external_content


class _ResearchHTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._texts: list[str] = []
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


def _research_tokenize(text: str) -> list[str]:
    tokens = [t for t in re.findall(r"[a-zA-Z0-9]+", (text or "").lower()) if t]
    return [t for t in tokens if t not in _RESEARCH_STOPWORDS]


def _research_extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
    tokens = _research_tokenize(text)
    seen = set()
    out: list[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_keywords:
            break
    return out


def _research_stable_unique(seq: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _research_expand_query_layers(
    keywords: list[str], user_text: str
) -> dict[str, list[str]]:
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


def _research_parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    try:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return None


def _research_parse_targets(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        t = item.strip().lower()
        if t in _PLANNER_TARGETS and t not in out:
            out.append(t)
    return out


def _research_is_redteam_query(text: str, targets: list[str] | None = None) -> bool:
    if targets and any(t in targets for t in ("cve", "exploit", "poc")):
        return True
    t = (text or "").lower()
    return any(h in t for h in _REDTEAM_HINTS)


def _research_needs_github_search(text: str, targets: list[str] | None = None) -> bool:
    if targets and any(t in targets for t in ("github", "repo", "code")):
        return True
    t = (text or "").lower()
    return any(h in t for h in _GIT_REPO_HINTS)


def _research_expand_github_layers(
    base_queries: list[str],
    user_text: str,
    keywords: list[str],
    *,
    redteam: bool = False,
    max_queries: int = 8,
) -> list[str]:
    seeds: list[str] = []
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

    queries: list[str] = []
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
        "not in dataset",
        "not in the dataset",
        "version not in dataset",
        "version not found",
        "unknown version",
        "not found in dataset",
        "not in training data",
        "new version",
        "latest version",
        "out of date dataset",
        "dataset is old",
    ]
    package_hints = [
        "package",
        "module",
        "library",
        "dependency",
        "pip",
        "npm",
        "pypi",
        "crate",
        "crates",
        "maven",
        "nuget",
        "gem",
        "rubygem",
        "packagist",
    ]
    return any(i in t for i in indicators) and any(h in t for h in package_hints)


def _research_guess_package_name(text: str) -> str | None:
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


def _research_extend_layers_for_package(
    layers: dict[str, list[str]], package_name: str | None
) -> dict[str, list[str]]:
    if not package_name:
        return layers
    layer_b = list(layers.get("layer_b") or [])
    layer_c = list(layers.get("layer_c") or [])

    layer_b.extend(
        [
            f"{package_name} latest version",
            f"{package_name} release notes",
            f"{package_name} changelog",
            f"{package_name} install instructions",
            f"{package_name} documentation",
        ]
    )

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
        query = [
            (k, v)
            for k, v in parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
        ]
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
    m = re.search(
        r"<title[^>]*>(.*?)</title>", html_text or "", re.IGNORECASE | re.DOTALL
    )
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


def _research_extract_date(text: str) -> str | None:
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
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        try:
            mo = months[mon.strip().lower()[:3]]
            return datetime.date(int(year), int(mo), int(day)).isoformat()
        except Exception:
            pass
    return None


def _research_compute_recency_score(date_str: str | None) -> float:
    if not date_str:
        return 0.0
    try:
        d = datetime.date.fromisoformat(date_str)
    except Exception:
        return 0.0
    days = (datetime.date.today() - d).days
    days = max(days, 0)
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


def _research_split_claims(text: str, max_claims: int = 3) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    claims = [p.strip() for p in parts if len(p.strip()) >= 20]
    return claims[:max_claims]


def _research_jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _research_pdf_to_text_if_available(pdf_bytes: bytes) -> str | None:
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
            subprocess.check_call(
                [pdftotext, pdf_path, txt_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if os.path.exists(txt_path):
                with open(txt_path, encoding="utf-8", errors="ignore") as f:
                    return f.read()
        except Exception:
            return None
    return None
