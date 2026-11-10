"""Shared data types: the contract between ingest, agent, app and eval.

Who produces and who reads each type:

- Chunk
    Produced by src/ingest (PDF parsing + chunking). Stored in the vector index
    and returned by retrieval with `score` filled in.
    Read by src/agent, which puts chunks into the LLM prompt and builds
    citations from them.

- Citation
    Produced by src/agent from the chunks the answer is based on.
    Read by src/app (shown under the answer) and eval (citation accuracy:
    does the cited page actually contain the figure?).

- Answer
    Produced by src/agent as the final result for one question.
    Read by src/app (displayed to the user) and eval (numeric accuracy via
    `numbers`, correct refusal rate via `found`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Chunk:
    """A piece of an annual report: a text passage or a table."""

    id: str
    text: str
    company: str
    year: int
    source_file: str
    page: int  # 1-based page number in the PDF
    kind: Literal["text", "table"] = "text"
    score: float | None = None  # retrieval similarity; None before retrieval


@dataclass
class Citation:
    """A pointer to the place in a report that supports an answer."""

    company: str
    year: int
    source_file: str
    page: int  # 1-based page number in the PDF
    snippet: str = ""


@dataclass
class Answer:
    """The agent's final answer to one question."""

    text: str
    citations: list[Citation] = field(default_factory=list)
    numbers: list[float] = field(default_factory=list)  # key figures, for eval
    found: bool = True  # False when the data is not in the reports
