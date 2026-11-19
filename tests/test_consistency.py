"""Tests for eval/consistency.py. All numbers are arbitrary test values, not report data."""

import pytest

from eval import consistency as c


def single(qid, label, value, company="A", file="a_2023.pdf", page=5):
    return {"id": qid, "company": company, "type": "numeric", "label": label,
            "gold_value": value, "source_file": file, "source_page": page}


def ratio(qid, inputs, company="A"):
    return {"id": qid, "company": company, "type": "numeric", "formula": "debt_to_equity",
            "inputs": [{"name": n, "label": l, "value": v, "source_file": "a_2023.pdf", "source_page": 6}
                       for n, l, v in inputs]}


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Net income 2023", ("net income", 2023)),
        ("Total equity at end of 2024", ("total equity", 2024)),
        ("  Total   assets 2022 ", ("total assets", 2022)),
        ("Something", None),
    ],
)
def test_parse_label(label, expected):
    assert c.parse_label(label) == expected


def test_figures_skip_todo_and_unlabelled():
    qs = [single("q1", "Net income 2023", "TODO"), {"id": "q2", "type": "numeric", "gold_value": 5},
          single("q3", "Net income 2023", 7)]
    assert [f["qid"] for f in c.figures(qs)] == ["q3"]


def test_same_figure_equal_values_ok():
    qs = [single("q1", "Total equity 2023", 100),
          ratio("q2", [("total_liabilities", "Total liabilities 2023", 50),
                       ("total_equity", "Total equity at end of 2023", 100)])]
    assert c.same_figure_warnings(c.figures(qs)) == []


def test_same_figure_different_values_warns():
    qs = [single("q1", "Total equity 2023", 100),
          ratio("q2", [("total_liabilities", "Total liabilities 2023", 50),
                       ("total_equity", "Total equity 2023", 101)])]
    warnings = c.same_figure_warnings(c.figures(qs))
    assert len(warnings) == 1 and "q1=100" in warnings[0] and "q2=101" in warnings[0]


def test_other_company_is_not_compared():
    qs = [single("q1", "Net income 2023", 1), single("q2", "Net income 2023", 2, company="B")]
    assert c.same_figure_warnings(c.figures(qs)) == []


def balance(assets, liabilities, equity):
    return [single("q1", "Total assets 2023", assets),
            ratio("q2", [("total_liabilities", "Total liabilities 2023", liabilities),
                         ("total_equity", "Total equity 2023", equity)])]


def test_balance_ok_within_tolerance():
    assert c.balance_warnings(c.figures(balance(1000, 600, 402))) == []


def test_balance_mismatch_warns():
    warnings = c.balance_warnings(c.figures(balance(1000, 600, 300)))
    assert len(warnings) == 1 and "q1" in warnings[0] and "q2" in warnings[0]


def test_balance_needs_all_three():
    qs = balance(1000, 600, 300)[1:]
    assert c.balance_warnings(c.figures(qs)) == []


def test_page_beyond_pdf_warns(tmp_path):
    (tmp_path / "a_2023.pdf").write_bytes(b"x")
    qs = [single("q1", "Net income 2023", 1, page=40), single("q2", "Revenue 2023", 1, page=3)]
    warnings = c.page_warnings(qs, tmp_path, page_count=lambda p: 30)
    assert warnings == ["q1: page 40 does not exist, a_2023.pdf has 30 pages"]


def test_page_check_skipped_without_pdf(tmp_path):
    qs = [single("q1", "Net income 2023", 1, page=999)]
    assert c.page_warnings(qs, tmp_path, page_count=lambda p: 1) == []


def test_check_consistency_on_template_has_no_warnings(tmp_path):
    qs = [single("q1", "Net income 2023", "TODO", page="TODO")]
    assert c.check_consistency(qs, tmp_path) == []
