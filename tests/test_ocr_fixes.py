"""Tests for src/ingest/ocr_fixes.py and how parse_pdf and build_index use it."""

import json

import pymupdf
import pytest

import scripts.build_index as build_index
from src.ingest.ocr_fixes import OcrFix, apply_fixes, load_ocr_fixes
from src.ingest.pdf_parser import parse_pdf_with_report

PAGE = (
    "In thousands of tenge   Notes   2024   2023\n"
    "Retained earnings   64,089,351   8,259,455\n"
    "Total equity and abilities   1,087,066,105   _1,001.785.007"
)
FIX = OcrFix(
    "kegoc_2024.pdf", 9,
    "Total equity and abilities   1,087,066,105   _1,001.785.007",
    "Total equity and liabilities   1,097,066,105   1,001,785,007",
    "page image, 2026-11-17",
)


def test_fix_replaces_the_whole_row():
    text, applied, problems = apply_fixes(PAGE, 9, [FIX])
    assert (applied, problems) == (1, [])
    assert text.splitlines()[2] == "Total equity and liabilities   1,097,066,105   1,001,785,007"
    assert text.splitlines()[:2] == PAGE.splitlines()[:2]


def test_fix_for_another_page_is_ignored():
    assert apply_fixes(PAGE, 8, [FIX]) == (PAGE, 0, [])


def test_missing_row_is_reported_and_text_unchanged():
    stale = OcrFix("kegoc_2024.pdf", 9, "Retained earnings   1   2", "x", "page image")
    text, applied, problems = apply_fixes(PAGE, 9, [stale])
    assert (text, applied) == (PAGE, 0)
    assert problems == ["OCR fix not applied (row not found): 'Retained earnings   1   2'"]


def test_part_of_a_row_does_not_match():
    partial = OcrFix("kegoc_2024.pdf", 9, "Retained earnings", "x", "page image")
    assert apply_fixes(PAGE, 9, [partial])[1] == 0


def test_row_found_twice_is_not_applied():
    page = PAGE + "\n" + PAGE.splitlines()[2]
    text, applied, problems = apply_fixes(page, 9, [FIX])
    assert (text, applied) == (page, 0)
    assert "row found 2 times" in problems[0]


def test_load_ocr_fixes(tmp_path):
    path = tmp_path / "ocr_fixes.json"
    path.write_text(json.dumps({"fixes": [
        {"file": "kegoc_2024.pdf", "page": 9, "old": FIX.old, "new": FIX.new, "checked": FIX.checked},
    ]}))
    assert load_ocr_fixes(path) == {"kegoc_2024.pdf": [FIX]}
    assert load_ocr_fixes(tmp_path / "none.json") == {}


@pytest.mark.parametrize("bad", [
    {"file": "a.pdf", "page": 1, "old": "x", "new": "y"},  # not checked
    {"file": "a.pdf", "page": 1, "old": "x\ny", "new": "y", "checked": "image"},  # two rows
])
def test_load_ocr_fixes_rejects_bad_entries(tmp_path, bad):
    path = tmp_path / "ocr_fixes.json"
    path.write_text(json.dumps({"fixes": [bad]}))
    with pytest.raises(ValueError):
        load_ocr_fixes(path)


def _make_pdf(path, rows):
    doc = pymupdf.open()
    page = doc.new_page()
    for n, row in enumerate(rows):
        page.insert_text((50, 60 + 14 * n), row, fontsize=9)
    doc.save(path)
    doc.close()


def test_parse_pdf_applies_fixes_before_chunking_and_units(tmp_path):
    path = tmp_path / "kegoc_2024.pdf"
    _make_pdf(path, ["In thousands of tenge", "Retained earnings 64,089,351 8,259,455"])
    fix = OcrFix("kegoc_2024.pdf", 1, "Retained earnings 64,089,351 8,259,455",
                 "Retained earnings 64,089,351 48,259,455", "page image")
    result = parse_pdf_with_report(path, "KEGOC", 2024, fixes=[fix])
    assert result.fixes_applied == 1
    assert "48,259,455" in result.chunks[0].text
    assert result.chunks[0].text.startswith("In thousands of tenge")


def test_build_index_applies_fixes_only_to_ocr_copy(tmp_path, monkeypatch):
    raw, ocr = tmp_path / "raw", tmp_path / "ocr"
    raw.mkdir()
    ocr.mkdir()
    (tmp_path / "reports.json").write_text(json.dumps({"reports": [
        {"file": "kegoc_2024.pdf", "company": "KEGOC", "year": 2024},
    ]}))
    _make_pdf(raw / "kegoc_2024.pdf", ["Total equity and abilities 1,087,066,105"])
    _make_pdf(ocr / "kegoc_2024.pdf", ["Total equity and abilities 1,087,066,105"])
    (tmp_path / "fixes.json").write_text(json.dumps({"fixes": [{
        "file": "kegoc_2024.pdf", "page": 1, "old": "Total equity and abilities 1,087,066,105",
        "new": "Total equity and liabilities 1,097,066,105", "checked": "page image",
    }]}))
    stored = []
    monkeypatch.setattr(build_index, "write_index", lambda chunks, d: stored.extend(chunks) or len(chunks))
    base = ["--manifest", str(tmp_path / "reports.json"), "--raw-dir", str(raw), "--ocr-dir", str(ocr),
            "--ocr-fixes", str(tmp_path / "fixes.json"), "--index-dir", str(tmp_path / "index")]

    assert build_index.main(base) == 0
    assert stored[0].text == "Total equity and liabilities 1,097,066,105"

    stored.clear()
    assert build_index.main(base + ["--no-ocr"]) == 0
    assert stored[0].text == "Total equity and abilities 1,087,066,105"
