import io
import zipfile
from pathlib import Path
from typing import List, Dict, Any
from fastapi import HTTPException

# Common text / code / config extensions
TEXT_EXTENSIONS = {
    # plain text / docs
    ".txt", ".md", ".rst", ".log",
    # Python
    ".py", ".pyw", ".pyi",
    # JS / TS / Node
    ".js", ".mjs", ".cjs", ".ts", ".tsx",
    # Web
    ".html", ".htm", ".css", ".scss", ".sass",
    # JSON / config
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    # C / C++ / ObjC
    ".c", ".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx", ".m", ".mm",
    # Java / Kotlin
    ".java", ".kt", ".kts",
    # C#
    ".cs",
    # Go / Rust
    ".go", ".rs",
    # PHP / Ruby
    ".php", ".phtml", ".rb", ".erb",
    # Shell / scripting
    ".sh", ".bash", ".zsh", ".ps1", ".psm1",
    # SQL / data
    ".sql", ".csv", ".tsv",
    # Misc dev files
    ".gradle", ".pom", ".xaml", ".vue", ".svelte",
}


def _looks_like_text(raw: bytes, sample_size: int = 2048) -> bool:
    """
    Heuristic to decide if a file is text:
    - No NUL bytes in a small sample
    - Majority of chars are printable / whitespace
    """
    if not raw:
        return False

    sample = raw[:sample_size]
    if b"\x00" in sample:
        return False

    text_chars = sum(
        chr(b).isprintable() or chr(b).isspace()
        for b in sample
    )
    ratio = text_chars / len(sample)
    return ratio > 0.7  # at least 70% printable → treat as text


def load_zip_resource(zip_path: Path, max_chars: int = 16000) -> str:
    """
    Load text content from a ZIP file for temporary LLM context.

    - Reads all subdirectories (zip paths like 'src/app/main.py', etc.).
    - Prefers known text/code-like extensions.
    - For unknown extensions, includes the file if it "looks like" text.
    - Concatenates content until max_chars is reached.
    """
    if not zip_path.exists() or not zip_path.is_file():
        raise HTTPException(status_code=404, detail=f"ZIP not found: {zip_path}")

    data = zip_path.read_bytes()

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    chunks: list[str] = []
    total = 0

    for info in zf.infolist():
        name = info.filename

        # skip directories
        if name.endswith("/"):
            continue

        ext = Path(name).suffix.lower()

        # read raw bytes once
        try:
            with zf.open(info) as f:
                raw = f.read()
        except Exception:
            continue

        # Decide if we include it:
        # 1) If extension is known text/code → include
        # 2) Else, include only if it "looks like" text
        if ext not in TEXT_EXTENSIONS and not _looks_like_text(raw):
            continue  # treat as binary / skip

        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            continue

        remaining = max_chars - total
        if remaining <= 0:
            break

        snippet = text[:remaining]
        chunks.append(f"=== {name} ===\n{snippet}")
        total += len(snippet)

    if not chunks:
        return "(no usable text files in ZIP)"

    return "\n\n".join(chunks)


def grep_zip_resource(
    zip_path: Path,
    keyword: str,
    before: int = 10,
    after: int = 10,
    max_matches: int = 50,
    ignore_case: bool = True,
) -> List[Dict[str, Any]]:
    """
    Grep for `keyword` across all text-ish files in a ZIP.

    Returns a list of matches:
      {
        "file": "path/in/zip/file.py",
        "match_line": <int>,          # 1-based
        "context": [ "...", ... ],    # lines around the match
        "context_start": <int>,       # first line number in context
        "context_end": <int>          # last line number in context
      }

    `before` / `after` control how many lines of context around each match.
    """
    if not zip_path.exists() or not zip_path.is_file():
        raise HTTPException(status_code=404, detail=f"ZIP not found: {zip_path}")

    if not keyword:
        raise HTTPException(status_code=400, detail="keyword is required")

    data = zip_path.read_bytes()

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    matches: List[Dict[str, Any]] = []
    needle = keyword.lower() if ignore_case else keyword

    for info in zf.infolist():
        name = info.filename

        # skip directories
        if name.endswith("/"):
            continue

        ext = Path(name).suffix.lower()

        # read raw bytes once
        try:
            with zf.open(info) as f:
                raw = f.read()
        except Exception:
            continue

        # Filter text-ish files (same logic as above)
        if ext not in TEXT_EXTENSIONS and not _looks_like_text(raw):
            continue

        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            continue

        lines = text.splitlines()
        for idx, line in enumerate(lines):
            hay = line.lower() if ignore_case else line
            if needle in hay:
                # Build context window
                start = max(0, idx - before)
                end = min(len(lines), idx + after + 1)
                context_block = lines[start:end]

                matches.append(
                    {
                        "file": name,
                        "match_line": idx + 1,
                        "context": context_block,
                        "context_start": start + 1,
                        "context_end": end,
                    }
                )

                if len(matches) >= max_matches:
                    return matches

    return matches
