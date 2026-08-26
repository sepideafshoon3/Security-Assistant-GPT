# src/tools/kali_tools_client.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


KALI_TOOLS_URL = "https://www.kali.org/tools/"


@dataclass
class KaliTool:
    slug: str           # e.g., "hydra"
    name: str           # e.g., "hydra"
    summary: str        # very short description or category


class KaliToolsClient:
    """
    Lightweight client around the Kali tools catalog.

    IMPORTANT:
    - We only pull high-level metadata (name, slug, short description).
    - We DO NOT scrape or store offensive one-liner attack examples.
    - Use this metadata to talk about tools defensively.
    """

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()

    def _normalize_tool_href(self, href: str) -> Optional[str]:
        """
        Normalize a tools href to a full https://www.kali.org/tools/<slug>/ URL.
        Return None if it's not a tool link.
        """
        if not href:
            return None

        href = href.strip()

        # Absolute URL already
        if href.startswith("http://") or href.startswith("https://"):
            parsed = urlparse(href)
            if "/tools/" not in parsed.path:
                return None
            return href

        # Relative URL on same host
        if href.startswith("/tools/"):
            return "https://www.kali.org" + href

        return None

    def list_tools(self, limit: Optional[int] = None) -> List[KaliTool]:
        """
        Fetch the 'all tools' page and extract a list of tools.

        This is a simple scraper that may need adjustment if the site layout changes.
        You should consider caching the result instead of calling this on every request.
        """
        resp = self.session.get(KALI_TOOLS_URL, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        tools: List[KaliTool] = []
        seen_slugs: set[str] = set()

        # The layout (from your HTML) uses a ton of <div class="card"><h3>…><ul><li><a href=".../tools/...">
        anchors = soup.select(
            "section#tools-list li > a[href*='/tools/'], "
            "section.tools-list li > a[href*='/tools/'], "
            "div.card li > a[href*='/tools/']"
        )

        for a in anchors:
            raw_href = a.get("href")
            full_href = self._normalize_tool_href(raw_href)
            if not full_href:
                continue

            parsed = urlparse(full_href)
            path = parsed.path  # e.g., "/tools/hydra/" or "/tools/sara/"
            parts = [p for p in path.strip("/").split("/") if p]

            # Expect at least ["tools", "<slug>"]
            if len(parts) < 2 or parts[0] != "tools":
                continue

            slug = parts[-1]
            if not slug or slug in seen_slugs:
                continue

            # Try to get only the direct text (without <i>, <span>, etc.)
            direct_text = a.find(text=True, recursive=False)
            if direct_text:
                name = direct_text.strip()
            else:
                # Fallback: full text or slug
                name = (a.get_text() or slug).strip()

            if not name:
                name = slug

            summary = f"Kali Linux tool (high-level metadata only; see {full_href} for details)."

            tools.append(
                KaliTool(
                    slug=slug,
                    name=name,
                    summary=summary,
                )
            )
            seen_slugs.add(slug)

            if limit is not None and len(tools) >= limit:
                break

        return tools

    def to_llm_context(self, tools: List[KaliTool], max_tools: int = 500000000000000000) -> str:
        """
        Build a compact text block summarizing tools for the LLM.

        Only high-level info, no usage commands.
        """
        if not tools:
            return "No Kali tools metadata available."

        lines = ["Kali tools metadata (high-level only, no exploit usage):"]
        for tool in tools[:max_tools]:
            lines.append(f"- {tool.name} (slug: {tool.slug}) – {tool.summary}")
        return "\n".join(lines)
