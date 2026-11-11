"""Calculator tools for the agent, and their JSON schemas for tool calling.

The LLM never does arithmetic itself: it reads figures from the reports with
`search_reports`, then calls one of the calculators below. Every calculator is
a pure function that rounds its result to 2 decimals and raises ValueError on a
zero denominator.

Units:
- percent_change, net_margin, roe return a percentage (12.5 means 12.5 %).
- ratio, debt_to_equity return a plain ratio (1.8 means 1.8x).
"""

from __future__ import annotations

from typing import Any, Callable


def _divide(numerator: float, denominator: float, name: str) -> float:
    if denominator == 0:
        raise ValueError(f"{name}: denominator is zero")
    return numerator / denominator


def percent_change(old: float, new: float) -> float:
    """Change from `old` to `new` in percent. Uses |old| so a loss turning into
    a smaller loss shows as growth."""
    return round(_divide(new - old, abs(old), "percent_change") * 100, 2)


def ratio(numerator: float, denominator: float) -> float:
    """numerator / denominator."""
    return round(_divide(numerator, denominator, "ratio"), 2)


def net_margin(net_income: float, revenue: float) -> float:
    """Net income as a percentage of revenue."""
    return round(_divide(net_income, revenue, "net_margin") * 100, 2)


def roe(net_income: float, equity: float) -> float:
    """Return on equity in percent: net income / equity * 100."""
    return round(_divide(net_income, equity, "roe") * 100, 2)


def debt_to_equity(total_liabilities: float, total_equity: float) -> float:
    """Total liabilities / total equity."""
    return round(_divide(total_liabilities, total_equity, "debt_to_equity"), 2)


# Name -> function, used by the agent to execute calculator tool calls.
CALCULATORS: dict[str, Callable[..., float]] = {
    "percent_change": percent_change,
    "ratio": ratio,
    "net_margin": net_margin,
    "roe": roe,
    "debt_to_equity": debt_to_equity,
}


def _number(description: str) -> dict[str, Any]:
    return {"type": "number", "description": description}


def _calculator_schema(name: str, description: str, params: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {p: _number(d) for p, d in params.items()},
                "required": list(params),
            },
        },
    }


SEARCH_REPORTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_reports",
        "description": (
            "Search the annual reports for passages and tables. Returns chunks "
            "with company, year, source_file, page and text. Use the figures "
            "exactly as written in the chunks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, e.g. 'net income'"},
                "company": {"type": "string", "description": "Company name, e.g. 'Halyk Bank'"},
                "year": {"type": "integer", "description": "Reporting year, e.g. 2023"},
            },
            "required": ["query"],
        },
    },
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    SEARCH_REPORTS_SCHEMA,
    _calculator_schema(
        "percent_change",
        "Percent change from an old value to a new value (e.g. year-over-year growth). Returns percent.",
        {"old": "Earlier value", "new": "Later value"},
    ),
    _calculator_schema(
        "ratio",
        "Divide one number by another. Returns a plain ratio.",
        {"numerator": "Numerator", "denominator": "Denominator"},
    ),
    _calculator_schema(
        "net_margin",
        "Net profit margin = net income / revenue. Returns percent.",
        {"net_income": "Net income", "revenue": "Revenue"},
    ),
    _calculator_schema(
        "roe",
        "Return on equity = net income / equity. Returns percent.",
        {"net_income": "Net income", "equity": "Total equity"},
    ),
    _calculator_schema(
        "debt_to_equity",
        "Debt-to-equity = total liabilities / total equity. Returns a plain ratio.",
        {"total_liabilities": "Total liabilities", "total_equity": "Total equity"},
    ),
]
