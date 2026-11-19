"""Cross-checks of the hand-filled gold figures. They warn, they never change values.

1. The same figure (company + label, e.g. "Halyk Bank / Net income 2023") must
   have the same value everywhere it is used: as a single-figure question and as
   an input of ratio questions.
2. Balance sheet: total assets = total liabilities + total equity for the same
   company and year, within 0.5%, when all three are filled in.
3. A source page cannot be larger than the number of pages of the PDF (only
   checked when the PDF is in data/raw/).

A warning means "look at the page again": a typo, an OCR misread or the wrong
column. It can also be a real restatement between two reports; then keep the
figure you read and note it in the question.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from eval.metrics import TODO

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
BALANCE_TOLERANCE = 0.005
_LABEL_RE = re.compile(r"^(?P<metric>.*?)\s+(?:at\s+end\s+of\s+)?(?P<year>\d{4})$", re.IGNORECASE)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_label(label: str) -> tuple[str, int] | None:
    """"Total equity at end of 2023" -> ("total equity", 2023); None if there is no year."""
    m = _LABEL_RE.match(" ".join(str(label or "").split()))
    if not m:
        return None
    return m.group("metric").casefold(), int(m.group("year"))


def figures(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every filled-in base figure: {qid, company, metric, year, value, source_file, source_page}."""
    found = []
    for q in questions:
        places = []
        if q.get("type") == "numeric" and "formula" not in q and q.get("label"):
            places.append((q["label"], q.get("gold_value"), q))
        for inp in q.get("inputs") or []:
            places.append((inp.get("label"), inp.get("value"), inp))
        for label, value, where in places:
            parsed = parse_label(label)
            if parsed is None or not _is_number(value):
                continue
            found.append({
                "qid": q.get("id"),
                "company": q.get("company"),
                "metric": parsed[0],
                "year": parsed[1],
                "value": value,
                "source_file": where.get("source_file"),
                "source_page": where.get("source_page"),
            })
    return found


def same_figure_warnings(found: list[dict[str, Any]]) -> list[str]:
    """Check 1: one figure, one value."""
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for f in found:
        groups.setdefault((f["company"], f["metric"], f["year"]), []).append(f)
    warnings = []
    for (company, metric, year), items in groups.items():
        if len({f["value"] for f in items}) > 1:
            where = ", ".join(f"{f['qid']}={f['value']:g} ({f['source_file']} p.{f['source_page']})" for f in items)
            warnings.append(f"{company} {metric} {year} has different values: {where}")
    return warnings


def balance_warnings(found: list[dict[str, Any]]) -> list[str]:
    """Check 2: assets = liabilities + equity."""
    values: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for f in found:
        if f["metric"] in ("total assets", "total liabilities", "total equity"):
            values.setdefault((f["company"], f["year"]), {})[f["metric"]] = f
    warnings = []
    for (company, year), v in values.items():
        if len(v) < 3:
            continue
        assets = v["total assets"]["value"]
        parts = v["total liabilities"]["value"] + v["total equity"]["value"]
        if assets and abs(assets - parts) > BALANCE_TOLERANCE * abs(assets):
            ids = ", ".join(sorted({x["qid"] for x in v.values()}))
            warnings.append(
                f"{company} {year}: total assets {assets:g} != total liabilities + total equity "
                f"{parts:g} (check {ids})"
            )
    return warnings


def _pdf_page_count(path: Path) -> int | None:
    try:
        import pymupdf

        with pymupdf.open(path) as doc:
            return doc.page_count
    except Exception:  # not installed or unreadable: skip the check
        return None


def page_warnings(
    questions: list[dict[str, Any]],
    raw_dir: Path = RAW_DIR,
    page_count: Callable[[Path], int | None] = _pdf_page_count,
) -> list[str]:
    """Check 3: the page exists in the PDF (skipped for PDFs that are not in raw_dir)."""
    counts: dict[str, int | None] = {}
    warnings = []
    for q in questions:
        for where in [q, *(q.get("inputs") or [])]:
            file, page = where.get("source_file"), where.get("source_page")
            if not file or not isinstance(page, int) or page == TODO:
                continue
            if file not in counts:
                path = raw_dir / file
                counts[file] = page_count(path) if path.exists() else None
            total = counts[file]
            if total is not None and page > total:
                warnings.append(f"{q.get('id')}: page {page} does not exist, {file} has {total} pages")
    return warnings


def check_consistency(questions: list[dict[str, Any]], raw_dir: Path = RAW_DIR) -> list[str]:
    """All warnings for the question file."""
    found = figures(questions)
    return same_figure_warnings(found) + balance_warnings(found) + page_warnings(questions, raw_dir)
