"""Vector search over the report index. Drop-in replacement for StubRetriever.

    Retriever().search("net income", k=5, company="halyk", year=2023) -> list[Chunk]

`company` is matched to a canonical name from data/reports.json, case-insensitively
("Halyk", "halyk bank" and "Halyk Bank" all work). An unknown company or an
invalid year returns [] instead of searching all reports, so the agent can say
the data is not in the reports. `score` is cosine similarity (1 = identical).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.ingest.index import DEFAULT_INDEX_DIR, open_collection
from src.ingest.manifest import DEFAULT_MANIFEST, load_manifest, resolve_company
from src.models import Chunk


class Retriever:
    """Semantic search over the chunks stored by scripts.build_index."""

    def __init__(
        self,
        index_dir: str | Path = DEFAULT_INDEX_DIR,
        manifest_path: str | Path = DEFAULT_MANIFEST,
        embedding_function: Any = None,
    ) -> None:
        self._collection = open_collection(index_dir, embedding_function)
        manifest = load_manifest(manifest_path)
        self._companies = manifest.companies
        self._aliases = manifest.aliases

    def search(
        self,
        query: str,
        k: int = 5,
        company: str | None = None,
        year: int | None = None,
    ) -> list[Chunk]:
        """Return up to k chunks most similar to `query`, best first."""
        filters: list[dict[str, Any]] = []
        if company is not None and str(company).strip():
            canonical = resolve_company(str(company), self._companies, self._aliases)
            if canonical is None:
                return []
            filters.append({"company": canonical})
        if year is not None and str(year).strip():
            try:
                filters.append({"year": int(year)})  # the LLM sometimes sends "2023"
            except (TypeError, ValueError):
                return []

        k = max(1, int(k))
        if self._collection.count() == 0:
            return []
        where = None if not filters else filters[0] if len(filters) == 1 else {"$and": filters}
        result = self._collection.query(
            query_texts=[query or ""],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return [
            Chunk(
                id=chunk_id,
                text=text,
                company=str(meta["company"]),
                year=int(meta["year"]),
                source_file=str(meta["source_file"]),
                page=int(meta["page"]),
                kind=str(meta.get("kind", "text")),  # type: ignore[arg-type]
                score=round(1.0 - float(distance), 4),
            )
            for chunk_id, text, meta, distance in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
            )
        ]
