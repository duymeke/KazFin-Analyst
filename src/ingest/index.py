"""Persistent ChromaDB index of report chunks.

One collection ("reports") with cosine distance. Each record stores the chunk
text as the document and company, year, source_file, page, kind as metadata.
The embedding function defaults to Chroma's built-in one (all-MiniLM-L6-v2,
downloaded once on first use); tests pass a small offline function instead.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from src.ingest.manifest import REPO_ROOT
from src.models import Chunk

DEFAULT_INDEX_DIR = REPO_ROOT / "data" / "index"
COLLECTION = "reports"


def client(index_dir: str | Path = DEFAULT_INDEX_DIR) -> chromadb.ClientAPI:
    """Persistent Chroma client with telemetry off (no network calls from Chroma itself)."""
    return chromadb.PersistentClient(
        path=str(index_dir), settings=Settings(anonymized_telemetry=False)
    )


def write_index(
    chunks: list[Chunk],
    index_dir: str | Path = DEFAULT_INDEX_DIR,
    embedding_function: Any = None,
) -> int:
    """Replace the collection in `index_dir` with `chunks`. Returns the number stored."""
    duplicates = [i for i, n in Counter(c.id for c in chunks).items() if n > 1]
    if duplicates:
        raise ValueError(f"duplicate chunk ids: {sorted(duplicates)[:5]}")

    db = client(index_dir)
    if COLLECTION in [c.name for c in db.list_collections()]:
        db.delete_collection(COLLECTION)
    kwargs: dict[str, Any] = {"configuration": {"hnsw": {"space": "cosine"}}}
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    collection = db.create_collection(COLLECTION, **kwargs)

    batch = db.get_max_batch_size()
    for start in range(0, len(chunks), batch):
        part = chunks[start : start + batch]
        collection.add(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            metadatas=[
                {
                    "company": c.company,
                    "year": c.year,
                    "source_file": c.source_file,
                    "page": c.page,
                    "kind": c.kind,
                }
                for c in part
            ],
        )
    return collection.count()


def open_collection(index_dir: str | Path = DEFAULT_INDEX_DIR, embedding_function: Any = None):
    """Open the existing collection; raises FileNotFoundError if the index was not built."""
    if not Path(index_dir).exists():
        raise FileNotFoundError(
            f"No index in {index_dir}. Build it with: python -m scripts.build_index"
        )
    db = client(index_dir)
    if COLLECTION not in [c.name for c in db.list_collections()]:
        raise FileNotFoundError(
            f"No '{COLLECTION}' collection in {index_dir}. Build it with: python -m scripts.build_index"
        )
    if embedding_function is not None:
        return db.get_collection(COLLECTION, embedding_function=embedding_function)
    return db.get_collection(COLLECTION)
