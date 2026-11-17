"""Tests for src/ingest/pdf_parser.py on a tiny PDF generated inside the test."""

import re

import pymupdf
import pytest

from src.ingest.pdf_parser import (
    find_unit,
    normalize_numbers,
    page_rows,
    parse_pdf,
    parse_pdf_with_report,
    split_text,
    table_to_markdown,
)

AGENT_CITE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")  # same character set as src/agent/agent.py
LONG_TEXT = " ".join(f"Sentence number {i} about loans and deposits of the bank." for i in range(60))


def _make_pdf(path, pages):
    """Write a PDF where each item of `pages` is the text of one page ("" = blank page)."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=9)
    doc.save(path)
    doc.close()


@pytest.fixture
def two_page_pdf(tmp_path):
    path = tmp_path / "halyk_2023.pdf"
    _make_pdf(path, [LONG_TEXT, "", "Net income for the year was reported in the statement."])
    return path


def test_page_numbers_are_one_based_and_blank_pages_skipped(two_page_pdf):
    chunks = parse_pdf(two_page_pdf, "Halyk Bank", 2023)
    assert {c.page for c in chunks} == {1, 3}  # page 2 is blank
    assert any("Net income" in c.text for c in chunks if c.page == 3)


def test_long_page_is_split_with_overlap(two_page_pdf):
    page1 = [c for c in parse_pdf(two_page_pdf, "Halyk Bank", 2023) if c.page == 1]
    assert len(page1) >= 3
    assert all(len(c.text) <= 1000 for c in page1)
    # the start of each chunk repeats text from the end of the previous one
    for prev, cur in zip(page1, page1[1:]):
        assert cur.text[:40] in prev.text


def test_chunk_ids_metadata_and_format(two_page_pdf):
    chunks = parse_pdf(two_page_pdf, "Halyk Bank", 2023)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert ids[0] == "halyk-2023-p1-0"
    for c in chunks:
        assert AGENT_CITE_RE.match(c.id)
        assert re.fullmatch(rf"halyk-2023-p{c.page}-\d+", c.id)
        assert (c.company, c.year, c.source_file, c.kind, c.score) == (
            "Halyk Bank", 2023, "halyk_2023.pdf", "text", None
        )


def test_company_and_year_come_from_arguments_not_pdf(tmp_path):
    path = tmp_path / "report.pdf"
    _make_pdf(path, ["Kcell JSC annual report for the year 2019."])
    [chunk] = parse_pdf(path, "KEGOC", 2024)
    assert (chunk.company, chunk.year, chunk.id) == ("KEGOC", 2024, "kegoc-2024-p1-0")


def test_unit_line_is_prepended_to_every_chunk_of_the_page(tmp_path):
    path = tmp_path / "kegoc_2024.pdf"
    _make_pdf(path, ["In thousands of tenge\n" + LONG_TEXT, "A page without units."])
    chunks = parse_pdf(path, "KEGOC", 2024)
    page1 = [c for c in chunks if c.page == 1]
    assert len(page1) >= 3
    assert all("In thousands of tenge" in c.text for c in page1)
    assert all(not c.text.startswith("Units:") for c in page1[:1])  # first chunk already has it
    assert all(c.text.startswith("Units: In thousands of tenge\n") for c in page1[1:])
    page2 = [c for c in chunks if c.page == 2]
    assert "Units:" not in page2[0].text


@pytest.mark.parametrize(
    "line, unit",
    [
        ("(Millions of Kazakhstani Tenge)", "(Millions of Kazakhstani Tenge)"),
        ("In millions of tenge", "In millions of tenge"),
        ("In thousands of tenge   Notes   2024   2023", "In thousands of tenge"),
        ("KZT million", "KZT million"),
        ("thousands of tenge were paid as dividends", None),
        ("Net income   610", None),
    ],
)
def test_find_unit(line, unit):
    assert find_unit("Header\n" + line + "\nBody") == unit


def test_scanned_page_is_reported(tmp_path):
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    page.insert_image(pymupdf.Rect(50, 50, 250, 250), pixmap=pix)
    doc.save(path)
    doc.close()
    result = parse_pdf_with_report(path, "Kcell", 2023)
    assert result.chunks == []
    assert result.problems == [(1, "no text layer, image only (scanned?)")]


def test_split_text_short_and_empty():
    assert split_text("short text") == ["short text"]
    assert split_text("   ") == []


def test_table_to_markdown_and_broken_tables():
    md, issue = table_to_markdown([["Item", "2023", None], ["Net income", "610", None]])
    assert issue is None
    assert md == "| Item | 2023 |\n|---|---|\n| Net income | 610 |"
    assert table_to_markdown([["only one cell"]])[0] == ""
    md, issue = table_to_markdown([["a", "", ""], ["", "b", ""], ["", "", "c"]])  # 6 of 9 empty
    assert md == "" and "empty cells" in issue


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Total assets   1.097.066.105   1.001.785.007",
         "Total assets   1,097,066,105   1,001,785,007"),
        ("Equity   2.345.678", "Equity   2,345,678"),
        ("Loss   (12.345.678)   -1.000.000", "Loss   (12,345,678)   -1,000,000"),
        ("It was 1.097.066.105.", "It was 1,097,066,105."),  # sentence-final dot stays
        # one dot: may be a decimal, not touched
        ("Net income   693.435   1.5   0.125", "Net income   693.435   1.5   0.125"),
        # not groups of exactly 3 digits, or part of a longer token
        ("31.12.2022   1.2.3   1.0970.661   1234.567.890   1.097.066.1",
         "31.12.2022   1.2.3   1.0970.661   1234.567.890   1.097.066.1"),
        ("693,435   1,097,066,105", "693,435   1,097,066,105"),  # commas already
    ],
)
def test_normalize_numbers(text, expected):
    assert normalize_numbers(text) == expected


def test_dot_thousands_normalized_in_chunks_and_tables(tmp_path):
    path = tmp_path / "kegoc_2024.pdf"
    _make_pdf(path, ["Total equity 1.097.066.105 and rate 13.5"])
    [chunk] = parse_pdf(path, "KEGOC", 2024)
    assert "1,097,066,105" in chunk.text and "13.5" in chunk.text
    md, _ = table_to_markdown([["Item", "2024"], ["Total equity", "1.097.066.105"]])
    assert "| Total equity | 1,097,066,105 |" in md


def _rotated_statement_page(rotation):
    """A landscape page shown rotated, like the Kcell 2024 scans (/Rotate 270).

    The text is written so that it reads normally as displayed; on the
    unrotated page it runs vertically.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    page.set_rotation(rotation)
    rows = [("Revenue", "235,467", "223,747"), ("Cost of sales", "(183,731)", "(156,008)")]
    for n, row in enumerate(rows):
        for x, text in zip((70, 400, 480), row):
            point = pymupdf.Point(x, 100 + 20 * n) * page.derotation_matrix
            page.insert_text(point, text, fontsize=10, rotate=rotation)
    return pymupdf.open("pdf", doc.tobytes())[0]


@pytest.mark.parametrize("rotation", [90, 270])
def test_page_rows_on_rotated_page_follows_displayed_rows(rotation):
    page = _rotated_statement_page(rotation)
    assert page.rotation == rotation
    assert page_rows(page) == (
        "Revenue   235,467   223,747\n"
        "Cost of sales   (183,731)   (156,008)"
    )
