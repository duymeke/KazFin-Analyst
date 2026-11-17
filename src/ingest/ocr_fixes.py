"""Hand-checked corrections of OCR text, read from data/ocr_fixes.json.

OCR misreads digits and words on scanned statement pages (e.g. KEGOC 2024
p. 9: "Total equity and abilities 1,087,066,105" instead of "Total equity and
liabilities 1,097,066,105"). Each fix replaces one whole row of a page's text,
and only fixes that were checked against the page image go into the file.

A fix is applied only when its `old` row occurs on the page exactly once, so a
fix never changes the wrong row; otherwise it is reported and the text is left
as it is (e.g. after OCR was redone and the row now reads differently).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.ingest.manifest import REPO_ROOT

DEFAULT_OCR_FIXES = REPO_ROOT / "data" / "ocr_fixes.json"


@dataclass(frozen=True)
class OcrFix:
    """Replace one row of the OCR text of a page."""

    file: str
    page: int  # 1-based
    old: str  # the whole row as the parser builds it (after number normalization)
    new: str
    checked: str  # how and when the new row was checked, e.g. "page image, 2026-11-17"


def load_ocr_fixes(path: str | Path = DEFAULT_OCR_FIXES) -> dict[str, list[OcrFix]]:
    """Fixes per file name. A missing file means no fixes."""
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    by_file: dict[str, list[OcrFix]] = {}
    for n, raw in enumerate(data.get("fixes", []), start=1):
        missing = [k for k in ("file", "page", "old", "new", "checked") if not raw.get(k)]
        if missing:
            raise ValueError(f"{path.name}: fix {n} is missing {', '.join(missing)}")
        fix = OcrFix(str(raw["file"]), int(raw["page"]), str(raw["old"]), str(raw["new"]),
                     str(raw["checked"]))
        if "\n" in fix.old or "\n" in fix.new:
            raise ValueError(f"{path.name}: fix {n} must be a single row")
        by_file.setdefault(fix.file, []).append(fix)
    return by_file


def apply_fixes(text: str, page: int, fixes: list[OcrFix]) -> tuple[str, int, list[str]]:
    """Apply the fixes for `page` to its text.

    Returns (text, number of fixes applied, problems). A fix whose `old` row
    is not on the page, or is there more than once, is not applied.
    """
    lines = text.split("\n")
    applied = 0
    problems: list[str] = []
    for fix in fixes:
        if fix.page != page:
            continue
        hits = [i for i, line in enumerate(lines) if line == fix.old]
        if len(hits) != 1:
            reason = "row not found" if not hits else f"row found {len(hits)} times"
            problems.append(f"OCR fix not applied ({reason}): {fix.old[:60]!r}")
            continue
        lines[hits[0]] = fix.new
        applied += 1
    return "\n".join(lines), applied, problems
