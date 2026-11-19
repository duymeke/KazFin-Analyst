"""Tests for eval/compute_gold.py. Input values are arbitrary test numbers, not report data."""

import json

import pytest

from eval import compute_gold
from src.agent import tools


def ratio_q(formula="roe", inputs=None, unit="%", qid="r1"):
    return {
        "id": qid,
        "type": "numeric",
        "unit": unit,
        "formula": formula,
        "inputs": inputs
        if inputs is not None
        else [{"name": "net_income", "value": 50}, {"name": "equity", "value": 400}],
        "gold_answer": "TODO",
        "gold_value": "TODO",
    }


def test_uses_the_agent_calculator():
    assert compute_gold.compute_item(ratio_q()) == tools.roe(50, 400)


@pytest.mark.parametrize(
    "formula,inputs",
    [
        ("percent_change", {"old": 80, "new": 100}),
        ("net_margin", {"net_income": 10, "revenue": 40}),
        ("debt_to_equity", {"total_liabilities": 900, "total_equity": 150}),
        ("ratio", {"numerator": 3, "denominator": 4}),
    ],
)
def test_every_formula(formula, inputs):
    item = ratio_q(formula, [{"name": k, "value": v} for k, v in inputs.items()])
    assert compute_gold.compute_item(item) == tools.CALCULATORS[formula](**inputs)


def test_todo_input_returns_none():
    item = ratio_q(inputs=[{"name": "net_income", "value": "TODO"}, {"name": "equity", "value": 400}])
    assert compute_gold.compute_item(item) is None


@pytest.mark.parametrize("bad", ["1,000", "50", None, True])
def test_non_number_input_is_an_error(bad):
    item = ratio_q(inputs=[{"name": "net_income", "value": bad}, {"name": "equity", "value": 400}])
    with pytest.raises(compute_gold.GoldError, match="number"):
        compute_gold.compute_item(item)


def test_unknown_formula():
    with pytest.raises(compute_gold.GoldError, match="unknown formula"):
        compute_gold.compute_item(ratio_q(formula="roa"))


def test_wrong_input_names():
    item = ratio_q(inputs=[{"name": "profit", "value": 1}, {"name": "equity", "value": 2}])
    with pytest.raises(compute_gold.GoldError, match="do not match"):
        compute_gold.compute_item(item)


def test_zero_denominator():
    item = ratio_q(inputs=[{"name": "net_income", "value": 1}, {"name": "equity", "value": 0}])
    with pytest.raises(compute_gold.GoldError):
        compute_gold.compute_item(item)


def test_apply_fills_gold_and_skips_others():
    single = {"id": "s1", "type": "numeric", "gold_value": "TODO"}
    pending = ratio_q(qid="r2", inputs=[{"name": "net_income", "value": "TODO"}, {"name": "equity", "value": 1}])
    ready = ratio_q(formula="debt_to_equity", unit="x",
                    inputs=[{"name": "total_liabilities", "value": 580}, {"name": "total_equity", "value": 100}])
    questions = [single, pending, ready]
    changes, n_pending = compute_gold.apply(questions)
    assert changes == [("r1", "TODO", 5.8)]
    assert n_pending == 1
    assert ready["gold_value"] == 5.8 and ready["gold_answer"] == "5.8 x"
    assert single["gold_value"] == "TODO" and pending["gold_value"] == "TODO"


def test_main_writes_file(tmp_path, capsys):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([ratio_q()]), encoding="utf-8")
    assert compute_gold.main(["--questions", str(path)]) == 0
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[0]["gold_value"] == tools.roe(50, 400)
    assert saved[0]["gold_answer"].endswith("%")


def test_main_dry_run_does_not_write(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([ratio_q()]), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    assert compute_gold.main(["--questions", str(path), "--dry-run"]) == 0
    assert path.read_text(encoding="utf-8") == before


def test_main_error_exit_code(tmp_path, capsys):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([ratio_q(formula="nope")]), encoding="utf-8")
    assert compute_gold.main(["--questions", str(path)]) == 1
    assert "Error" in capsys.readouterr().out
