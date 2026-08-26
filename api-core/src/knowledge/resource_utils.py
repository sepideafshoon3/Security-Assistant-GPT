from typing import List, Tuple, Optional, Iterable


def combine_resources(
    resources: Optional[Iterable[Optional[Tuple[str, str]]]],
    max_chars: int = 16000,
) -> str:
    """
    Combine multiple named resources into a single text block.

    resources: iterable of (name, text) or None entries.
               Any None or empty-text entries are skipped safely.
    """
    if not resources:
        return "(no resource content)"

    chunks: List[str] = []
    total = 0

    for item in resources:
        # Shield: skip None or malformed items
        if not item or not isinstance(item, tuple) or len(item) != 2:
            continue

        name, text = item

        if not text:
            continue  # skip empty/None text

        remaining = max_chars - total
        if remaining <= 0:
            break

        snippet = text[:remaining]
        chunks.append(f"=== RESOURCE: {name} ===\n{snippet}")
        total += len(snippet)

    if not chunks:
        return "(no resource content)"

    return "\n\n".join(chunks)
