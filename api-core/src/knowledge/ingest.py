from __future__ import annotations

from pathlib import Path
from typing import List
import math
import uuid
import json


def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """
    Split large text into overlapping chunks.
    Simple char-based chunking; good enough for v1.
    """
    chunks: List[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap  # overlap previous chunk

    return chunks


def ingest_large_file(file_path: Path, base_dir: Path) -> str:
    """
    Ingest a huge file:
    - Reads it
    - Chunks it
    - Stores chunks under data/knowledge-base/<resource_id>/
    Returns resource_id.
    """
    text = file_path.read_text(errors="ignore")

    resource_id = str(uuid.uuid4())
    resource_dir = base_dir / resource_id
    resource_dir.mkdir(parents=True, exist_ok=True)

    chunks = chunk_text(text, chunk_size=1500, overlap=200)

    meta = {
        "id": resource_id,
        "original_file": str(file_path),
        "num_chunks": len(chunks),
    }

    # Save chunks
    for i, chunk in enumerate(chunks):
        (resource_dir / f"chunk_{i:05d}.txt").write_text(chunk)

    # Save meta
    (resource_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    return resource_id
