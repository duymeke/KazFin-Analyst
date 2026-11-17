"""Hybrid search over the report index. Drop-in replacement for StubRetriever.

    Retriever().search("net income", k=5, company="halyk", year=2023) -> list[Chunk]

`company` is matched to a canonical name from data/reports.json, case-insensitively
("Halyk", "halyk bank" and "Halyk Bank" all work). An unknown company or an
invalid year returns [] instead of searching all reports, so the agent can say
the data is not in the reports.

Ranking (hybrid=True, the default) fuses three rankings of the chunks that pass
the company/year filter with reciprocal rank fusion (RRF):
- vector search (embeddings, finds paraphrases),
- BM25 keyword search (exact words such as "revenue", "equity"),
- table rows: a row whose label starts with the content words of the query and
  that has figures ("Revenue from contracts with customers   235,467   223,747").
  Statement pages mention a line item once, next to its figures, while the
  notes mention it in many sentences; vector search alone ranks the notes higher.
hybrid=False is plain vector search (kept for comparison in scripts/eval_retrieval.py).

`score`: with hybrid=True it is the fused RRF score divided by the highest
possible one (a chunk ranked first by all three rankings), so it lies in 0-1
and 1 means "best possible match". A raw RRF value is tiny (at most 3/61, about
0.05) and would look like "not relevant". With hybrid=False it is the cosine
similarity (1 = identical).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.ingest.index import DEFAULT_INDEX_DIR, open_collection
from src.ingest.manifest import DEFAULT_MANIFEST, load_manifest, resolve_company
from src.models import Chunk

# Reciprocal rank fusion: a chunk gets 1 / (RRF_K + rank) from every ranking it is in,
# and the sums are sorted. RRF_K = 60 is the value from the original RRF paper
# (Cormack et al., 2009); it keeps one first place from outweighing several good ranks.
RRF_K = 60

# BM25 (Okapi BM25) scores a chunk by how often the query words occur in it,
# weighted by how rare each word is in the chunks searched (idf). Two parameters:
# - k1 controls term frequency saturation: the first occurrence of a word adds
#   most, each further one adds less, and the score approaches a limit set by
#   k1. With k1 = 0 only "word present or not" counts; large k1 is close to raw
#   counts. 1.2-2.0 is the usual range; 1.5 is a common default.
# - b controls length normalization: a long chunk contains more words by chance,
#   so its term frequency is divided by (1 - b + b * length / average length).
#   b = 0 ignores length, b = 1 normalizes fully; 0.75 is the usual default.
BM25_K1 = 1.5
BM25_B = 0.75

_WORD_RE = re.compile(r"[a-z]+")
_FIGURE_RE = re.compile(r"\(?\d{1,3}(?:,\d{3})+\)?")  # 235,467 or (183,731)
# Words that do not identify a line item, so they are ignored when matching a
# query to a row label. Chosen on the "dev" cases of data/retrieval_cases.json.
_LABEL_STOPWORDS = frozenset(
    "the of and for at in a as to total statement income position financial balance "
    "december loss or profit".split()
)
_LABEL_WORDS = 8  # how many words at the start of a row count as its label


def words(text: str) -> list[str]:
    """Lowercase words (letters only); numbers and punctuation are dropped."""
    return _WORD_RE.findall(text.lower())


def bm25_scores(query: str, docs: list[list[str]]) -> list[float]:
    """BM25 score of each tokenized document for `query` (0 if no query word occurs).

    score(doc) = sum over query words w of
        idf(w) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc) / avg_len))
    with tf = count of w in doc and idf(w) = ln(1 + (N - df + 0.5) / (df + 0.5)),
    N = number of docs, df = number of docs containing w.
    """
    if not docs:
        return []
    avg_len = sum(map(len, docs)) / len(docs) or 1.0
    df = Counter(w for doc in docs for w in set(doc))
    n = len(docs)
    terms = words(query)
    scores = []
    for doc in docs:
        tf = Counter(doc)
        score = 0.0
        for term in terms:
            if term in tf:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                norm = tf[term] + BM25_K1 * (1 - BM25_B + BM25_B * len(doc) / avg_len)
                score += idf * tf[term] * (BM25_K1 + 1) / norm
        scores.append(score)
    return scores


def row_label_score(query: str, text: str) -> float:
    """How well a table row of `text` matches the query's line item; 0 if no row does.

    A row counts only if it has a figure like 235,467. Its label is the words
    before the first figure. The score is the share of the query's content words
    in the label, plus 0.5 if the label starts with one of them.
    """
    terms = [w for w in words(query) if w not in _LABEL_STOPWORDS] or words(query)
    if not terms:
        return 0.0
    best = 0.0
    for line in text.lower().splitlines():
        if not _FIGURE_RE.search(line):
            continue
        label = words(_FIGURE_RE.split(line, maxsplit=1)[0])[:_LABEL_WORDS]
        if not label:
            continue
        score = sum(t in label for t in terms) / len(terms)
        if label[0] in terms:
            score += 0.5
        best = max(best, score)
    return best


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Fuse rankings (lists of ids, best first) into (id, score) pairs, best first.

    The score is normalized to 0-1 by the highest possible sum, len(rankings) / (k + 1),
    which a chunk gets only if it is first in every ranking.
    """
    if not rankings:
        return []
    fused: Counter[str] = Counter()
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] += 1.0 / (k + rank)
    best_possible = len(rankings) / (k + 1)
    # ties keep the order of the first ranking
    first = {item: i for i, item in enumerate(rankings[0])}
    order = sorted(fused, key=lambda item: (-fused[item], first.get(item, len(first))))
    return [(item, fused[item] / best_possible) for item in order]


class Retriever:
    """Search over the chunks stored by scripts.build_index."""

    def __init__(
        self,
        index_dir: str | Path = DEFAULT_INDEX_DIR,
        manifest_path: str | Path = DEFAULT_MANIFEST,
        embedding_function: Any = None,
        hybrid: bool = True,
    ) -> None:
        self._collection = open_collection(index_dir, embedding_function)
        manifest = load_manifest(manifest_path)
        self._companies = manifest.companies
        self._aliases = manifest.aliases
        self._hybrid = hybrid
        # keyword search needs all chunk texts; about 3,000 chunks, read once
        self._texts: dict[str, str] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._words: dict[str, list[str]] = {}
        if hybrid and self._collection.count():
            stored = self._collection.get(include=["documents", "metadatas"])
            for chunk_id, text, meta in zip(stored["ids"], stored["documents"], stored["metadatas"]):
                self._texts[chunk_id] = text
                self._meta[chunk_id] = meta
                self._words[chunk_id] = words(text)

    def search(
        self,
        query: str,
        k: int = 5,
        company: str | None = None,
        year: int | None = None,
    ) -> list[Chunk]:
        """Return up to k chunks for `query`, best first."""
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

        if not self._hybrid:
            return self._dense(query, k, where)

        wanted = {key: value for f in filters for key, value in f.items()}
        candidates = [
            cid for cid, meta in self._meta.items()
            if all(meta.get(key) == value for key, value in wanted.items())
        ]
        if not candidates:
            return []
        # vector ranking of every candidate of this company and year (a few hundred chunks)
        dense = self._dense(query, len(candidates), where)

        bm25 = bm25_scores(query, [self._words[cid] for cid in candidates])
        keyword = [cid for score, cid in sorted(zip(bm25, candidates), key=lambda p: -p[0]) if score > 0]
        rows = [(row_label_score(query, self._texts[cid]), cid) for cid in candidates]
        table_rows = [cid for score, cid in sorted(rows, key=lambda p: -p[0]) if score > 0]

        ranked = rrf([[c.id for c in dense], keyword, table_rows])[:k]
        return [self._chunk(cid, round(score, 4)) for cid, score in ranked]

    def _dense(self, query: str, n: int, where: dict[str, Any] | None) -> list[Chunk]:
        result = self._collection.query(
            query_texts=[query or ""],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return [
            _to_chunk(chunk_id, text, meta, round(1.0 - float(distance), 4))
            for chunk_id, text, meta, distance in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
            )
        ]

    def _chunk(self, chunk_id: str, score: float | None) -> Chunk:
        return _to_chunk(chunk_id, self._texts[chunk_id], self._meta[chunk_id], score)


def _to_chunk(chunk_id: str, text: str, meta: dict[str, Any], score: float | None) -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        company=str(meta["company"]),
        year=int(meta["year"]),
        source_file=str(meta["source_file"]),
        page=int(meta["page"]),
        kind=str(meta.get("kind", "text")),  # type: ignore[arg-type]
        score=score,
    )
