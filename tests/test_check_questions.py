"""Tests for eval/check_questions.py: a small fake manifest, arbitrary test numbers."""

import copy
import json

import pytest

from eval import check_questions as cq

MANIFEST = {
    "halyk_2022.pdf": {"file": "halyk_2022.pdf", "company": "Halyk Bank", "year": 2022},
    "halyk_2023.pdf": {"file": "halyk_2023.pdf", "company": "Halyk Bank", "year": 2023},
    "kegoc_2023.pdf": {"file": "kegoc_2023.pdf", "company": "KEGOC", "year": 2023},
}

SINGLE = {
    "id": "q1", "question": "q", "company": "Halyk Bank", "year": 2023, "type": "numeric",
    "unit": "million KZT", "gold_answer": "TODO", "gold_value": "TODO",
    "source_file": "halyk_2023.pdf", "source_page": "TODO",
}
RATIO = {
    "id": "q2", "question": "q", "company": "Halyk Bank", "year": 2023, "type": "numeric",
    "unit": "%", "formula": "percent_change",
    "inputs": [
        {"name": "old", "label": "a", "value": "TODO", "source_file": "halyk_2022.pdf", "source_page": "TODO"},
        {"name": "new", "label": "b", "value": 120, "source_file": "halyk_2023.pdf", "source_page": 12},
    ],
    "gold_answer": "TODO", "gold_value": "TODO",
}
TEXT = {
    "id": "q3", "question": "q", "company": "KEGOC", "year": 2023, "type": "text", "unit": "",
    "gold_answer": "TODO", "gold_keywords": ["TODO"], "gold_value": None,
    "source_file": "kegoc_2023.pdf", "source_page": "TODO",
}
NOT_FOUND = {
    "id": "q4", "question": "q", "company": "Kaspi.kz", "year": 2023, "type": "not_found", "unit": "",
    "gold_answer": "TODO", "gold_value": None, "source_file": None, "source_page": None,
}


def valid():
    return copy.deepcopy([SINGLE, RATIO, TEXT, NOT_FOUND])


def errors_for(change):
    questions = valid()
    change(questions)
    return cq.check(questions, MANIFEST)


def test_valid_file_has_no_errors():
    assert cq.check(valid(), MANIFEST) == []


def test_comparative_year_report_is_allowed():
    def change(q):
        q[0]["year"] = 2022  # 2022 figure read in the 2023 report

    assert errors_for(change) == []


@pytest.mark.parametrize(
    "change,expected",
    [
        (lambda q: q[1].update(id="q1"), "duplicate id"),
        (lambda q: q[0].pop("unit"), "missing field 'unit'"),
        (lambda q: q[0].update(type="number"), "type must be"),
        (lambda q: q[0].update(year="2023"), "year must be an integer"),
        (lambda q: q[0].update(company="Kaspi.kz"), "not in data/reports.json"),
        (lambda q: q[0].update(source_file="halyk_2019.pdf"), "not in data/reports.json"),
        (lambda q: q[0].update(source_file="kegoc_2023.pdf"), "belongs to KEGOC"),
        (lambda q: q[0].update(year=2021), "is the 2023 report"),
        (lambda q: q[0].update(source_page=0), "source_page must be"),
        (lambda q: q[0].update(gold_value="1,000"), "gold_value must be a number"),
        (lambda q: q[0].update(unit="thousand KZT"), "unit for Halyk Bank"),
        (lambda q: q[1].update(formula="roa"), "unknown formula"),
        (lambda q: q[1].update(unit="x"), "unit for percent_change"),
        (lambda q: q[1]["inputs"][0].update(name="previous"), "inputs for percent_change"),
        (lambda q: q[1]["inputs"][0].update(value="100"), "value must be a number"),
        (lambda q: q[1]["inputs"][0].update(source_file="kegoc_2023.pdf"), "belongs to KEGOC"),
        (lambda q: q[1].update(inputs=[]), "non-empty inputs"),
        (lambda q: q[2].update(gold_keywords=[]), "gold_keywords"),
        (lambda q: q[2].update(gold_value=1), "text question must have gold_value null"),
        (lambda q: q[3].update(gold_value=5), "not_found question must have gold_value null"),
        (lambda q: q[3].update(source_file="halyk_2023.pdf"), "source_file null"),
    ],
)
def test_detects_problem(change, expected):
    errors = errors_for(change)
    assert any(expected in e for e in errors), errors


def test_not_a_list():
    assert cq.check({"id": "q1"}, MANIFEST) == ["the file must contain a JSON list of questions"]


def test_summary_counts_and_todo():
    questions = valid()
    questions[3]["gold_answer"] = "Not found in the reports"  # q4 becomes ready
    text = cq.summary(questions)
    assert "Halyk Bank" in text and "Kaspi.kz" in text
    assert "Ready (no TODO): 1 of 4" in text


def write(tmp_path, questions):
    qpath = tmp_path / "q.json"
    qpath.write_text(questions if isinstance(questions, str) else json.dumps(questions), encoding="utf-8")
    mpath = tmp_path / "reports.json"
    mpath.write_text(json.dumps({"reports": list(MANIFEST.values())}), encoding="utf-8")
    return ["--questions", str(qpath), "--manifest", str(mpath)]


def test_main_ok(tmp_path, capsys):
    assert cq.main(write(tmp_path, valid())) == 0
    assert "OK" in capsys.readouterr().out


def test_main_invalid_exit_code(tmp_path, capsys):
    questions = valid()
    questions[0]["type"] = "bad"
    assert cq.main(write(tmp_path, questions)) == 1
    assert "problem" in capsys.readouterr().out


def test_main_bad_json(tmp_path, capsys):
    assert cq.main(write(tmp_path, "[{")) == 1
    assert "Invalid JSON" in capsys.readouterr().out


def test_load_manifest_drops_skipped(tmp_path):
    path = tmp_path / "reports.json"
    path.write_text(json.dumps({"reports": [
        {"file": "a.pdf", "company": "A", "year": 2023},
        {"file": "b.pdf", "company": "B", "year": 2023, "skip": "broken"},
    ]}), encoding="utf-8")
    assert list(cq.load_manifest(path)) == ["a.pdf"]
