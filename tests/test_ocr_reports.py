"""Tests for scripts/ocr_reports.py helpers. ocrmypdf itself is not run."""

import pymupdf

from scripts.ocr_reports import check_pages, empty_pages, ocr_command


def _make_pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=9)
    doc.save(path)
    doc.close()


def test_empty_pages(tmp_path):
    _make_pdf(tmp_path / "a.pdf", ["text", "", "more", ""])
    assert empty_pages(tmp_path / "a.pdf") == [2, 4]


def test_check_pages(tmp_path):
    src, good, short, changed = (tmp_path / f"{n}.pdf" for n in ("src", "good", "short", "changed"))
    _make_pdf(src, ["Page one", ""])
    _make_pdf(good, ["Page one", "OCR text of the image page"])
    _make_pdf(short, ["Page one"])
    _make_pdf(changed, ["Page 1", "OCR text"])
    assert check_pages(src, good) is None
    assert check_pages(src, short) == "1 pages instead of 2"
    assert check_pages(src, changed) == "text of page 1 changed"


def test_ocr_command_skips_text_pages_and_keeps_plain_pdf(tmp_path):
    cmd = ocr_command(tmp_path / "in.pdf", tmp_path / "out.pdf")
    assert cmd[0] == "ocrmypdf"
    assert "--skip-text" in cmd
    assert cmd[cmd.index("-l") + 1] == "eng"
    assert cmd[cmd.index("--output-type") + 1] == "pdf"
    assert cmd[-2:] == [str(tmp_path / "in.pdf"), str(tmp_path / "out.pdf")]
