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
from src.ingest.retriever import Retriever, bm25_scores, row_label_score, rrf
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


# --- hybrid search: BM25, table rows, RRF ------------------------------------


def test_bm25_scores_match_a_hand_calculation():
    """Three tiny documents, query "revenue", k1 = 1.5, b = 0.75.

    N = 3, df(revenue) = 2, idf = ln(1 + (3 - 2 + 0.5) / (2 + 0.5)) = ln(1.6) = 0.470004
    average length = (2 + 3 + 1) / 3 = 2
    d1 = "revenue grew": tf = 1, length 2
        1 * 2.5 / (1 + 1.5 * (0.25 + 0.75 * 2 / 2)) = 2.5 / 2.5 = 1       -> 0.470004
    d2 = "revenue revenue note": tf = 2, length 3
        2 * 2.5 / (2 + 1.5 * (0.25 + 0.75 * 3 / 2)) = 5 / 4.0625 = 1.2308 -> 0.578467
    d3 = "cash": no query word                                              -> 0
    The second "revenue" in d2 adds only 23% (tf saturation, k1), and d2 is
    longer than average, which lowers it a little (length normalization, b).
    """
    docs = [["revenue", "grew"], ["revenue", "revenue", "note"], ["cash"]]
    scores = bm25_scores("revenue", docs)
    assert scores[0] == pytest.approx(0.470004, abs=1e-6)
    assert scores[1] == pytest.approx(0.578467, abs=1e-6)
    assert scores[2] == 0.0


def test_bm25_rare_word_counts_more_than_common_word():
    docs = [["equity", "note"], ["equity", "total"], ["equity", "cash"]]
    # "equity" is in every doc (low idf), "cash" in one (high idf)
    scores = bm25_scores("equity cash", docs)
    assert scores[2] > scores[0] == scores[1] > 0


def test_row_label_score_prefers_a_table_row_with_figures():
    statement = "Revenue from contracts with customers   22   235,467   223,747\nCost of sales   (183,731)"
    note = "Revenue is recognized when control passes. Revenue from roaming is shown net.\nSee Note 22."
    assert row_label_score("revenue", statement) == 1.5  # all words, and the label starts with one
    assert row_label_score("revenue", note) == 0.0  # no row with a figure
    # stop words such as "total" and "statement" are ignored
    assert row_label_score("total revenue statement", statement) == 1.5
    assert row_label_score("cash", statement) == 0.0


def test_rrf_order_and_normalized_score():
    fused = rrf([["a", "b", "c"], ["b", "a"], ["b"]])
    assert [item for item, _ in fused] == ["b", "a", "c"]
    scores = dict(fused)
    # b: 1/62 + 1/61 + 1/61 out of the best possible 3/61
    assert scores["b"] == pytest.approx((1 / 62 + 2 / 61) / (3 / 61))
    assert all(0 < s <= 1 for s in scores.values())
    assert dict(rrf([["x"], ["x"], ["x"]]))["x"] == pytest.approx(1.0)
    assert rrf([]) == []


@pytest.fixture
def statement_retriever(tmp_path):
    """A statement page with the figure and two note pages that repeat the word."""
    manifest = tmp_path / "reports.json"
    manifest.write_text(json.dumps({"reports": [{"file": "kcell_2024.pdf", "company": "Kcell", "year": 2024}]}))
    chunks = [
        _chunk("Kcell", "kcell", 2024, 25, "Revenue recognition. Revenue is recognized when control of the "
               "services passes to the customer. Revenue from prepaid contracts is deferred."),
        _chunk("Kcell", "kcell", 2024, 26, "Call out revenue is recognized based on airtime. Interconnect "
               "revenue and roaming revenue are recognized when the service is provided."),
        _chunk("Kcell", "kcell", 2024, 9, "CONSOLIDATED STATEMENT OF COMPREHENSIVE INCOME\n"
               "Revenue from contracts with customers   22   235,467   223,747\n"
               "Cost of sales   23   (183,731)   (156,008)"),
    ]
    index_dir = tmp_path / "index"
    write_index(chunks, index_dir, embedding_function=HashEmbedding())
    return lambda hybrid: Retriever(index_dir=index_dir, manifest_path=manifest,
                                    embedding_function=HashEmbedding(), hybrid=hybrid)


def test_hybrid_ranks_the_statement_row_first(statement_retriever):
    dense = statement_retriever(False).search("revenue", k=3, company="Kcell", year=2024)
    hybrid = statement_retriever(True).search("revenue", k=3, company="Kcell", year=2024)
    assert dense[0].page != 9  # word counts alone favour the notes
    assert hybrid[0].page == 9
    assert all(0 < c.score <= 1 for c in hybrid)
    assert [c.score for c in hybrid] == sorted((c.score for c in hybrid), reverse=True)


def test_hybrid_keeps_filters(statement_retriever):
    hybrid = statement_retriever(True)
    assert hybrid.search("revenue", company="Halyk") == []
    assert hybrid.search("revenue", company="Kcell", year=2023) == []
    assert len(hybrid.search("revenue", k=2, company="Kcell")) == 2
