"""Tests for src/ingest/index.py and src/ingest/retriever.py.

Uses a small offline embedding function (word hashing) and a temporary index,
so no model download, network or real reports are needed. The chunk texts are
placeholders, not figures from the real reports.
"""

import hashlib
import json
import re

import numpy as np
import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from src.ingest.index import write_index
from src.ingest.manifest import resolve_company
from src.ingest.retriever import Retriever
from src.models import Chunk


class HashEmbedding(EmbeddingFunction[Documents]):
    """Bag-of-words vector: each word adds 1 to one of 64 hashed dimensions."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            v = np.zeros(64, dtype=np.float32)
            for word in re.findall(r"[a-z]+", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
            v[0] += 0.01  # never an all-zero vector
            vectors.append(v)
        return vectors

    @staticmethod
    def name() -> str:
        return "test-hash"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "HashEmbedding":
        return HashEmbedding()


def _chunk(company, slug, year, page, text, kind="text"):
    return Chunk(
        id=f"{slug}-{year}-p{page}-0",
        text=text,
        company=company,
        year=year,
        source_file=f"{slug}_{year}.pdf",
        page=page,
        kind=kind,
    )


CHUNKS = [
    _chunk("Halyk Bank", "halyk", 2023, 10, "net income for the year placeholder", "table"),
    _chunk("Halyk Bank", "halyk", 2022, 11, "net income for the year placeholder"),
    _chunk("Halyk Bank", "halyk", 2023, 12, "loans to customers placeholder"),
    _chunk("KEGOC", "kegoc", 2024, 5, "total equity placeholder", "table"),
    _chunk("Kcell", "kcell", 2023, 7, "net income for the year placeholder"),
]


@pytest.fixture
def retriever(tmp_path):
    manifest = tmp_path / "reports.json"
    manifest.write_text(
        json.dumps(
            {
                "reports": [
                    {"file": "halyk_2023.pdf", "company": "Halyk Bank", "year": 2023},
                    {"file": "kegoc_2024.pdf", "company": "KEGOC", "year": 2024},
                    {"file": "kcell_2023.pdf", "company": "Kcell", "year": 2023},
                ],
                "aliases": {"KEGOC": ["Kazakhstan Electricity Grid Operating Company"]},
            }
        )
    )
    index_dir = tmp_path / "index"
    assert write_index(CHUNKS, index_dir, embedding_function=HashEmbedding()) == len(CHUNKS)
    return Retriever(index_dir=index_dir, manifest_path=manifest, embedding_function=HashEmbedding())


def test_returns_chunks_with_metadata_and_score(retriever):
    results = retriever.search("net income", k=5)
    assert results and all(isinstance(c, Chunk) for c in results)
    assert results[0].text.startswith("net income")
    assert all(c.score is not None and -1.0 <= c.score <= 1.0 for c in results)
    assert [c.score for c in results] == sorted((c.score for c in results), reverse=True)
    top = next(c for c in results if c.id == "halyk-2023-p10-0")
    assert (top.company, top.year, top.page, top.kind, top.source_file) == (
        "Halyk Bank", 2023, 10, "table", "halyk_2023.pdf"
    )


@pytest.mark.parametrize("name", ["halyk", "Halyk", "HALYK", "halyk bank", "Halyk Bank", "Halyk Bank JSC"])
def test_company_filter_is_tolerant(retriever, name):
    results = retriever.search("net income", k=10, company=name)
    assert results
    assert {c.company for c in results} == {"Halyk Bank"}


def test_company_alias(retriever):
    results = retriever.search("total equity", company="Kazakhstan Electricity Grid Operating Company JSC")
    assert [c.id for c in results] == ["kegoc-2024-p5-0"]


def test_unknown_company_returns_nothing(retriever):
    assert retriever.search("net income", company="Kaspi") == []


def test_year_filter_int_and_str(retriever):
    for year in (2022, "2022"):
        results = retriever.search("net income", k=10, company="halyk", year=year)
        assert [c.id for c in results] == ["halyk-2022-p11-0"]
    assert retriever.search("net income", year="last year") == []


def test_year_filter_without_company(retriever):
    results = retriever.search("net income", k=10, year=2023)
    assert {c.year for c in results} == {2023}
    assert {c.company for c in results} == {"Halyk Bank", "Kcell"}


def test_k_limits_results(retriever):
    assert len(retriever.search("placeholder", k=2)) == 2


def test_missing_index_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_index"):
        Retriever(index_dir=tmp_path / "nope")


@pytest.mark.parametrize(
    "name, expected",
    [("kcell", "Kcell"), ("KEGOC JSC", "KEGOC"), ("k", None), ("", None), ("bank", "Halyk Bank")],
)
def test_resolve_company(name, expected):
    assert resolve_company(name, ["Halyk Bank", "KEGOC", "Kcell"]) == expected
