from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
import json
import math
import os
from openai import OpenAI
from dotenv import load_dotenv  # if you're using python-dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY not set in environment")
client = OpenAI()
DATA_DIR = BASE_DIR / "data"
KNOWLEDGE_FILE = DATA_DIR / "knowledge-base" / "knowledge.txt"

def embed_texts(texts: List[str], model: str | None = None) -> List[List[float]]:
    """
    Get embeddings for a list of texts.
    Model defaults to OPENAI_EMBEDDING_MODEL / LLM_EMBEDDING_MODEL from env.
    """
    from src.llm.model_config import get_embedding_model

    model = model or get_embedding_model()
    # Batch call for efficiency
    resp = client.embeddings.create(
        model=model,
        input=texts,
    )
    return [item.embedding for item in resp.data]


def l2_distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def build_embeddings_index(resource_dir: Path, model: str | None = None) -> None:
    """
    For each chunk_XXXXX.txt, compute embedding and store in embeddings.jsonl
    """
    from src.llm.model_config import get_embedding_model

    model = model or get_embedding_model()
    chunk_files = sorted(resource_dir.glob("chunk_*.txt"))
    texts = [f.read_text(errors="ignore") for f in chunk_files]
    vectors = embed_texts(texts, model=model)

    out_path = resource_dir / "embeddings.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for file_path, vec in zip(chunk_files, vectors):
            record = {
                "file": file_path.name,
                "embedding": vec,
            }
            f.write(json.dumps(record) + "\n")


def load_embeddings_index(resource_dir: Path) -> List[Tuple[str, List[float]]]:
    """
    Load embeddings for a resource: return list of (filename, vector).
    """
    idx_path = resource_dir / "embeddings.jsonl"
    if not idx_path.exists():
        return []

    out: List[Tuple[str, List[float]]] = []
    with idx_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            out.append((rec["file"], rec["embedding"]))
    return out


def semantic_search(
    question: str,
    resource_dir: Path,
    top_k: int = 5,
    model: str | None = None,
) -> List[str]:
    """
    Given a question, return the contents of top_k most similar chunks.
    """
    from src.llm.model_config import get_embedding_model

    model = model or get_embedding_model()
    # embed question
    q_vec = embed_texts([question], model=model)[0]
    index = load_embeddings_index(resource_dir)
    if not index:
        return []

    # score
    scored = []
    for fname, vec in index:
        dist = l2_distance(q_vec, vec)
        scored.append((dist, fname))

    scored.sort(key=lambda x: x[0])
    top = scored[:top_k]

    snippets: List[str] = []
    for _, fname in top:
        path = resource_dir / fname
        snippets.append(path.read_text(errors="ignore"))

    return snippets

def load_knowledge_text(max_chars: int = 16000) -> str:
    """
    Load the shared knowledge file for chat context.
    """
    if not KNOWLEDGE_FILE.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Knowledge file not found: {KNOWLEDGE_FILE}",
        )
    text = KNOWLEDGE_FILE.read_text(errors="ignore")
    return text[:max_chars]
