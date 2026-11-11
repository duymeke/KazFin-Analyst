"""Stand-in for src/ingest/retriever.py until the real retriever is ready.

Same interface as the real one: `search(query, k, company, year) -> list[Chunk]`.

The figures below are FAKE, made up for testing the agent loop. They are not
taken from Halyk Bank's real reports and must never be used in evaluation.
"""

from __future__ import annotations

import re

from src.models import Chunk

STUB_CHUNKS: list[Chunk] = [
    Chunk(
        id="halyk-2023-p87-0",
        text=(
            "[STUB DATA] Consolidated statement of profit or loss for 2023. "
            "Total revenue: 1,450,000 million KZT. Net income: 610,000 million KZT."
        ),
        company="Halyk Bank",
        year=2023,
        source_file="halyk_2023.pdf",
        page=87,
        kind="table",
    ),
    Chunk(
        id="halyk-2023-p85-0",
        text=(
            "[STUB DATA] Consolidated statement of financial position as at 31 December 2023. "
            "Total liabilities: 14,200,000 million KZT. Total equity: 2,450,000 million KZT."
        ),
        company="Halyk Bank",
        year=2023,
        source_file="halyk_2023.pdf",
        page=85,
        kind="table",
    ),
    Chunk(
        id="halyk-2022-p79-0",
        text=(
            "[STUB DATA] Consolidated statement of profit or loss for 2022. "
            "Total revenue: 1,180,000 million KZT. Net income: 520,000 million KZT."
        ),
        company="Halyk Bank",
        year=2022,
        source_file="halyk_2022.pdf",
        page=79,
        kind="table",
    ),
    Chunk(
        id="halyk-2022-p77-0",
        text=(
            "[STUB DATA] Consolidated statement of financial position as at 31 December 2022. "
            "Total liabilities: 12,600,000 million KZT. Total equity: 2,050,000 million KZT."
        ),
        company="Halyk Bank",
        year=2022,
        source_file="halyk_2022.pdf",
        page=77,
        kind="table",
    ),
]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


class StubRetriever:
    """Keyword-overlap search over a few hard-coded chunks."""

    def __init__(self, chunks: list[Chunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else STUB_CHUNKS

    def search(
        self,
        query: str,
        k: int = 5,
        company: str | None = None,
        year: int | None = None,
    ) -> list[Chunk]:
        candidates = [
            c
            for c in self.chunks
            if (company is None or company.lower() in c.company.lower())
            and (year is None or c.year == year)
        ]
        query_words = _words(query)
        results = []
        for c in candidates:
            overlap = len(query_words & _words(c.text))
            if overlap:
                score = overlap / max(len(query_words), 1)
                results.append(Chunk(**{**c.__dict__, "score": round(score, 3)}))
        results.sort(key=lambda c: c.score or 0, reverse=True)
        return results[:k]
