"""Tests for eval/metrics.py. The numbers here are arbitrary test values, not report data."""

import pytest

from eval import metrics
from src.models import Answer, Citation


def item(**overrides):
    base = {
        "id": "t1",
        "question": "q",
        "company": "Halyk Bank",
        "year": 2023,
        "type": "numeric",
        "gold_answer": "a",
        "gold_value": 100.0,
        "unit": "",
        "source_file": "halyk_2023.pdf",
        "source_page": 10,
    }
    base.update(overrides)
    return base


def cite(company="Halyk Bank", year=2023, page=10, source_file="halyk_2023.pdf"):
    return Citation(company=company, year=year, source_file=source_file, page=page)


def ratio_item(**overrides):
    base = item(
        formula="roe",
        inputs=[
            {"name": "net_income", "label": "a", "value": 1.0, "source_file": "halyk_2023.pdf", "source_page": 12},
            {"name": "equity", "label": "b", "value": 2.0, "source_file": "halyk_2023.pdf", "source_page": 11},
        ],
    )
    del base["source_file"], base["source_page"]
    base.update(overrides)
    return base


# --- is_ready ---------------------------------------------------------------

def test_is_ready_true_when_filled():
    assert metrics.is_ready(item())


@pytest.mark.parametrize("field", ["gold_answer", "gold_value", "source_page"])
def test_is_ready_false_with_todo(field):
    assert not metrics.is_ready(item(**{field: "TODO"}))


def test_is_ready_not_found_with_nulls():
    assert metrics.is_ready(item(type="not_found", gold_value=None, source_page=None))


def test_is_ready_ratio_with_filled_inputs():
    assert metrics.is_ready(ratio_item())


@pytest.mark.parametrize("field", ["value", "source_page"])
def test_is_ready_false_with_todo_input(field):
    r = ratio_item()
    r["inputs"][1][field] = "TODO"
    assert not metrics.is_ready(r)


def test_is_ready_false_with_todo_keyword():
    assert not metrics.is_ready(item(type="text", gold_value=None, gold_keywords=["TODO"]))


# --- numeric_correct --------------------------------------------------------

@pytest.mark.parametrize("value", [100.0, 101.0, 99.0, 100.5])
def test_numeric_within_one_percent(value):
    assert metrics.numeric_correct(Answer("a", numbers=[value]), 100.0)


@pytest.mark.parametrize("value", [101.01, 98.9, -100.0])
def test_numeric_outside_one_percent(value):
    assert not metrics.numeric_correct(Answer("a", numbers=[value]), 100.0)


def test_numeric_any_number_matches():
    assert metrics.numeric_correct(Answer("a", numbers=[5.0, 2023.0, 100.2]), 100.0)


def test_numeric_empty_numbers():
    assert not metrics.numeric_correct(Answer("a"), 100.0)


@pytest.mark.parametrize("gold", [None, "TODO"])
def test_numeric_missing_gold(gold):
    assert not metrics.numeric_correct(Answer("a", numbers=[100.0]), gold)


def test_numeric_negative_gold():
    assert metrics.numeric_correct(Answer("a", numbers=[-50.4]), -50.0)
    assert not metrics.numeric_correct(Answer("a", numbers=[50.0]), -50.0)


def test_numeric_zero_gold_uses_absolute_tolerance():
    assert metrics.numeric_correct(Answer("a", numbers=[0.0]), 0.0)
    assert metrics.numeric_correct(Answer("a", numbers=[0.005]), 0.0)
    assert not metrics.numeric_correct(Answer("a", numbers=[0.5]), 0.0)


def test_numeric_custom_tolerance():
    assert metrics.numeric_correct(Answer("a", numbers=[104.0]), 100.0, tolerance=0.05)


# --- citation_correct -------------------------------------------------------

def test_citation_match():
    assert metrics.citation_correct(Answer("a", citations=[cite()]), item())


def test_citation_company_case_and_spaces_ignored():
    assert metrics.citation_correct(Answer("a", citations=[cite(company=" halyk  bank ")]), item())


@pytest.mark.parametrize(
    "bad", [cite(page=11), cite(source_file="halyk_2022.pdf"), cite(company="Kcell")]
)
def test_citation_mismatch(bad):
    assert not metrics.citation_correct(Answer("a", citations=[bad]), item())


def test_citation_one_of_many():
    answer = Answer("a", citations=[cite(page=1), cite(page=10)])
    assert metrics.citation_correct(answer, item())


def test_citation_no_citations():
    assert not metrics.citation_correct(Answer("a"), item())


@pytest.mark.parametrize("page", [None, "TODO"])
def test_citation_missing_gold_page(page):
    assert not metrics.citation_correct(Answer("a", citations=[cite()]), item(source_page=page))


def test_citation_comparative_column_counts():
    # 2022 figure read in the 2023 report: the citation year is the report year (2023)
    gold = item(year=2022, source_file="halyk_2023.pdf", source_page=12)
    assert metrics.citation_correct(Answer("a", citations=[cite(year=2023, page=12)]), gold)


def test_citation_wrong_file_same_page():
    assert not metrics.citation_correct(Answer("a", citations=[cite(source_file="halyk_2022.pdf")]), item())


@pytest.mark.parametrize("page,ok", [(12, True), (11, True), (10, False)])
def test_citation_ratio_any_input_page(page, ok):
    assert metrics.citation_correct(Answer("a", citations=[cite(page=page)]), ratio_item()) is ok


# --- text_correct -----------------------------------------------------------

def text_item(keywords):
    return item(type="text", gold_value=None, gold_keywords=keywords)


def test_text_all_keywords_case_insensitive():
    assert metrics.text_correct(Answer("Audited by  ernst & YOUNG LLP"), text_item(["Ernst & Young"]))


def test_text_missing_keyword():
    assert not metrics.text_correct(Answer("Audited by KPMG"), text_item(["Ernst & Young", "LLP"]))


@pytest.mark.parametrize("keywords", [[], ["TODO"], None])
def test_text_no_usable_keywords(keywords):
    assert not metrics.text_correct(Answer("anything"), text_item(keywords))


def test_text_refusal_is_not_correct():
    assert not metrics.text_correct(Answer("KPMG not found", found=False), text_item(["KPMG"]))


# --- not_found_correct ------------------------------------------------------

def test_not_found_refused():
    assert metrics.not_found_correct(Answer("Not found", found=False), item(type="not_found"))


def test_not_found_answered_anyway():
    assert not metrics.not_found_correct(Answer("It was 5", found=True), item(type="not_found"))


def test_not_found_wrong_type():
    assert not metrics.not_found_correct(Answer("Not found", found=False), item(type="numeric"))


# --- score_item / summarize -------------------------------------------------

def test_score_item_applicability():
    assert metrics.score_item(Answer("a"), item(type="numeric"))["not_found"] is None
    text_scores = metrics.score_item(Answer("a"), item(type="text", gold_keywords=["a"]))
    assert text_scores["numeric"] is None and text_scores["citation"] is False
    assert text_scores["text"] is True
    nf_scores = metrics.score_item(Answer("a", found=False), item(type="not_found"))
    assert nf_scores == {"numeric": None, "citation": None, "text": None, "not_found": True}


def test_summarize_counts_only_applicable():
    scores = [
        {"numeric": True, "citation": True, "not_found": None},
        {"numeric": False, "citation": True, "not_found": None},
        {"numeric": None, "citation": None, "not_found": True},
    ]
    s = metrics.summarize(scores)
    assert s["numeric"] == {"correct": 1, "total": 2, "accuracy": 0.5}
    assert s["citation"] == {"correct": 2, "total": 2, "accuracy": 1.0}
    assert s["not_found"] == {"correct": 1, "total": 1, "accuracy": 1.0}


def test_summarize_empty():
    s = metrics.summarize([])
    assert s["numeric"] == {"correct": 0, "total": 0, "accuracy": None}
