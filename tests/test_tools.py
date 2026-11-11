import pytest

from src.agent import tools
from src.agent.tools import (
    CALCULATORS,
    TOOL_SCHEMAS,
    debt_to_equity,
    net_margin,
    percent_change,
    ratio,
    roe,
)


def test_percent_change_growth():
    assert percent_change(100, 125) == 25.0


def test_percent_change_decline():
    assert percent_change(200, 150) == -25.0


def test_percent_change_negative_base():
    # a loss of 100 shrinking to a loss of 50 is an improvement
    assert percent_change(-100, -50) == 50.0


def test_percent_change_rounds_to_two_decimals():
    assert percent_change(3, 4) == 33.33


def test_ratio():
    assert ratio(10, 4) == 2.5


def test_net_margin():
    assert net_margin(50, 200) == 25.0


def test_roe():
    assert roe(30, 240) == 12.5


def test_debt_to_equity():
    assert debt_to_equity(900, 500) == 1.8


@pytest.mark.parametrize(
    "func, args",
    [
        (percent_change, (0, 10)),
        (ratio, (5, 0)),
        (net_margin, (5, 0)),
        (roe, (5, 0)),
        (debt_to_equity, (5, 0)),
    ],
)
def test_zero_denominator_raises(func, args):
    with pytest.raises(ValueError):
        func(*args)


def test_every_calculator_has_a_schema():
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert set(CALCULATORS) <= schema_names
    assert "search_reports" in schema_names


def test_schema_params_match_function_signatures():
    import inspect

    for schema in TOOL_SCHEMAS:
        name = schema["function"]["name"]
        if name == "search_reports":
            continue
        params = list(schema["function"]["parameters"]["properties"])
        assert params == list(inspect.signature(getattr(tools, name)).parameters)
