# src/search/searchsploit_client.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List
import subprocess
import json


@dataclass
class SearchsploitResult:
    edb_id: str
    title: str
    platform: str | None
    exploit_type: str | None
    path: str | None  # local path to PoC file (we do NOT read it)


class SearchsploitClient:
    """
    Wrapper around the `searchsploit` CLI tool.

    IMPORTANT:
    - We only use metadata returned from searchsploit.
    - We DO NOT open or read the actual exploit files.
    """

    def __init__(self, binary: str = "searchsploit") -> None:
        self.binary = binary

    def search(self, query: str, limit: int = 5) -> List[SearchsploitResult]:
        """
        Run `searchsploit -j <query>` and return metadata results.
        """
        try:
            # searchsploit -j outputs JSON
            proc = subprocess.run(
                [self.binary, "-j", query],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
        except FileNotFoundError:
            # searchsploit not installed / not in PATH
            return []
        except subprocess.TimeoutExpired:
            return []

        if proc.returncode != 0:
            # searchsploit error, or no results
            return []

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []

        results: List[SearchsploitResult] = []

        # Typical structure: {"RESULTS_EXPLOIT": [...], "RESULTS_SHELLCODE": [...]}
        exploits = data.get("RESULTS_EXPLOIT", []) or []
        for item in exploits[:limit]:
            edb_id = str(item.get("EDB-ID", "")).strip()
            title = str(item.get("Title", "")).strip()
            platform = item.get("Platform")
            exploit_type = item.get("Type")
            path = item.get("Path")

            if not edb_id and not title:
                continue

            results.append(
                SearchsploitResult(
                    edb_id=edb_id,
                    title=title,
                    platform=platform,
                    exploit_type=exploit_type,
                    path=path,
                )
            )

        return results
