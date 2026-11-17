"""Tests for the metrics in scripts/eval_retrieval.py and the shape of data/retrieval_cases.json."""

import json

from scripts.eval_retrieval import DEFAULT_CASES, first_hit, summarize


def test_first_hit():
    assert first_hit([145, 12, 13], {12, 13}) == 2
    assert first_hit([145, 153], {12}) is None
    assert first_hit([], {1}) is None


def test_summarize():
    s = summarize([1, 2, None, 6])
    assert s["hit@1"] == 0.25
    assert s["hit@5"] == 0.5
    assert abs(s["mrr"] - (1 + 1 / 2 + 1 / 6) / 4) < 1e-9


def test_cases_file_is_consistent():
    cases = json.loads(DEFAULT_CASES.read_text(encoding="utf-8"))["cases"]
    assert {c["split"] for c in cases} == {"dev", "heldout"}
    for c in cases:
        assert c["statement_page"] in c["pages"], c
        assert c["value"] and c["checked"] and c["query"]
