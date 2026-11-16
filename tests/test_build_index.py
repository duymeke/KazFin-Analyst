"""Tests for scripts/build_index.py and manifest.source_path(): OCR copies are read
when they exist, but chunks keep the original file name and page numbers."""

import json

import pymupdf
import pytest

import scripts.build_index as build_index
from src.ingest.manifest import source_path
from src.ingest.pdf_parser import parse_pdf


def _make_pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=9)
    doc.save(path)
    doc.close()


@pytest.fixture
def dirs(tmp_path):
    raw, ocr = tmp_path / "raw", tmp_path / "ocr"
    raw.mkdir()
    ocr.mkdir()
    manifest = tmp_path / "reports.json"
    manifest.write_text(json.dumps({"reports": [
        {"file": "kegoc_2024.pdf", "company": "KEGOC", "year": 2024},
        {"file": "kcell_2023.pdf", "company": "Kcell", "year": 2023},
    ]}))
    # kegoc: raw page 2 is "image only" (blank here), the OCR copy has its text
    _make_pdf(raw / "kegoc_2024.pdf", ["Cover page", ""])
    _make_pdf(ocr / "kegoc_2024.pdf", ["Cover page", "Total equity   OCR text"])
    # kcell: no OCR copy, raw is used
    _make_pdf(raw / "kcell_2023.pdf", ["Raw text only"])
    return raw, ocr, manifest


def test_source_path_prefers_ocr_copy(dirs):
    raw, ocr, _ = dirs
    assert source_path("kegoc_2024.pdf", raw, ocr) == ocr / "kegoc_2024.pdf"
    assert source_path("kcell_2023.pdf", raw, ocr) == raw / "kcell_2023.pdf"
    assert source_path("kegoc_2024.pdf", raw, None) == raw / "kegoc_2024.pdf"


def test_source_name_overrides_file_name(tmp_path):
    path = tmp_path / "copy.pdf"
    _make_pdf(path, ["Some text"])
    [chunk] = parse_pdf(path, "KEGOC", 2024, source_name="kegoc_2024.pdf")
    assert chunk.source_file == "kegoc_2024.pdf"
    assert parse_pdf(path, "KEGOC", 2024)[0].source_file == "copy.pdf"


def _run(monkeypatch, tmp_path, *extra):
    stored = []

    def fake_write_index(chunks, index_dir):
        stored.extend(chunks)
        return len(chunks)

    monkeypatch.setattr(build_index, "write_index", fake_write_index)
    raw, ocr, manifest = tmp_path / "raw", tmp_path / "ocr", tmp_path / "reports.json"
    code = build_index.main([
        "--manifest", str(manifest), "--raw-dir", str(raw), "--ocr-dir", str(ocr),
        "--index-dir", str(tmp_path / "index"), *extra,
    ])
    assert code == 0
    return stored


def test_build_index_reads_ocr_copy_with_original_names_and_pages(dirs, monkeypatch, tmp_path):
    chunks = _run(monkeypatch, tmp_path)
    kegoc = [c for c in chunks if c.company == "KEGOC"]
    assert [(c.page, c.id) for c in kegoc] == [(1, "kegoc-2024-p1-0"), (2, "kegoc-2024-p2-0")]
    assert "OCR text" in kegoc[1].text
    assert all(c.source_file == "kegoc_2024.pdf" for c in kegoc)
    [kcell] = [c for c in chunks if c.company == "Kcell"]
    assert (kcell.source_file, kcell.page, kcell.text) == ("kcell_2023.pdf", 1, "Raw text only")


def test_build_index_no_ocr_flag_uses_raw(dirs, monkeypatch, tmp_path):
    chunks = _run(monkeypatch, tmp_path, "--no-ocr")
    assert [c.page for c in chunks if c.company == "KEGOC"] == [1]  # page 2 has no text in raw
    assert not any("OCR text" in c.text for c in chunks)
