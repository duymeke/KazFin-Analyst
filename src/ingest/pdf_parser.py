"""Turn one report PDF into Chunks: page text (PyMuPDF) and tables (pdfplumber).

For every page:
- Text: the page is always indexed as text, even when a table is found on it,
  because statement tables in these PDFs often have no ruling lines and
  pdfplumber misses them. Words are regrouped into visual rows by their
  position, so a table row stays on one line ("Total assets  1.097.066.105 ...")
  instead of one cell per line. Long pages are split into ~1000-character
  chunks with 150 characters of overlap.
- Tables: pdfplumber's extract_tables(), converted to markdown, kind="table".
- Numbers: dot thousands separators (KEGOC: "1.097.066.105") are rewritten
  to commas ("1,097,066,105"), so all companies use one format. Numbers with
  a single dot ("1.5", "693.435") are left alone, they may be decimals.
- Units: a unit line such as "(Millions of Kazakhstani Tenge)" is detected once
  per page and prepended to every chunk of that page that does not contain it.

Company and year are passed in by the caller (from data/reports.json); they are
never read from the PDF. Problems (pages without a text layer, broken tables)
are collected in ParseResult.problems so the build report can show them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
import pymupdf

from src.ingest.manifest import company_slug
from src.models import Chunk

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MAX_TABLE_CHARS = 1500
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")  # what the agent's citation regex accepts

# Words closer than this (in points) on one row are joined with one space,
# wider gaps (table columns) with three.
_ROW_TOLERANCE = 3.0
_COLUMN_GAP = 12.0

# A unit line at the start of a row: "In thousands of tenge", "(Millions of Kazakhstani Tenge)",
# "KZT million". It must be followed by the end of the row or a column gap,
# so ordinary sentences ("thousands of tenge were paid") do not match.
_UNIT_RE = re.compile(
    r"^\(?\s*(?:"
    r"(?:in\s+)?(?:millions?|thousands?|billions?)\s+of\s+(?:kazakhstani\s+)?(?:tenge|kzt)"
    r"|(?:in\s+)?(?:kzt|tenge)\s*(?:millions?|thousands?|billions?|mln|bn|['’]000)"
    r")\s*\)?(?=$|\s{3})",
    re.IGNORECASE,
)

# 1-3 digits, then two or more ".ddd" groups; not part of a longer number,
# so "1.5", "693.435", "31.12.2022" and "1.097.066.1" do not match.
_DOT_THOUSANDS_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3}){2,}(?!\d|[.,]\d)")


@dataclass
class ParseResult:
    """Chunks of one PDF plus what the build report needs."""

    chunks: list[Chunk]
    page_count: int
    pages_without_tables: int = 0  # pages with text where pdfplumber found no usable table
    problems: list[tuple[int, str]] = field(default_factory=list)  # (page, description)


def parse_pdf(
    path: str | Path, company: str, year: int, source_name: str | None = None
) -> list[Chunk]:
    """Parse one report PDF into text and table chunks with 1-based page numbers.

    `source_name` is the file name stored in chunks (default: the name of `path`);
    build_index passes the original name when it parses the OCR copy.
    """
    return parse_pdf_with_report(path, company, year, source_name).chunks


def parse_pdf_with_report(
    path: str | Path, company: str, year: int, source_name: str | None = None
) -> ParseResult:
    """Like parse_pdf(), but also returns page counts and parsing problems."""
    path = Path(path)
    source_name = source_name or path.name
    slug = company_slug(company)
    chunks: list[Chunk] = []
    problems: list[tuple[int, str]] = []
    pages_without_tables = 0

    with pymupdf.open(path) as doc, pdfplumber.open(path) as plumber:
        page_count = len(doc)
        for index, page in enumerate(doc):
            page_no = index + 1
            text = normalize_numbers(page_rows(page))
            if not text.strip():
                if page.get_images():
                    problems.append((page_no, "no text layer, image only (scanned?)"))
                continue

            unit = find_unit(text)
            pieces = [("text", piece) for piece in split_text(text)]

            try:
                tables = plumber.pages[index].extract_tables()
            except Exception as exc:  # a broken page must not stop the whole file
                tables = []
                problems.append((page_no, f"pdfplumber failed: {type(exc).__name__}"))
            good_tables = 0
            for t_no, table in enumerate(tables, start=1):
                markdown, issue = table_to_markdown(table)
                if issue:
                    problems.append((page_no, f"table {t_no}: {issue}"))
                if markdown:
                    good_tables += 1
                    pieces.extend(("table", part) for part in split_table(markdown))
            if good_tables == 0:
                pages_without_tables += 1

            for n, (kind, piece) in enumerate(pieces):
                if unit and unit.lower() not in piece.lower():
                    piece = f"Units: {unit}\n{piece}"
                chunk_id = f"{slug}-{year}-p{page_no}-{n}"
                if not ID_RE.match(chunk_id):
                    raise ValueError(f"invalid chunk id {chunk_id!r}")
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        text=piece,
                        company=company,
                        year=year,
                        source_file=source_name,
                        page=page_no,
                        kind=kind,
                    )
                )

    return ParseResult(chunks, page_count, pages_without_tables, problems)


def page_rows(page: pymupdf.Page) -> str:
    """Page text with words regrouped into visual rows (top to bottom, left to right)."""
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[list[tuple]] = []
    row_y: float | None = None
    for word in words:
        y = (word[1] + word[3]) / 2
        if row_y is None or abs(y - row_y) > _ROW_TOLERANCE:
            rows.append([])
            row_y = y
        rows[-1].append(word)

    lines = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        line = row[0][4]
        for prev, word in zip(row, row[1:]):
            line += ("   " if word[0] - prev[2] > _COLUMN_GAP else " ") + word[4]
        lines.append(line)
    return "\n".join(lines)


def normalize_numbers(text: str) -> str:
    """Rewrite dot thousands separators to commas: "1.097.066.105" -> "1,097,066,105".

    Only numbers with two or more dot-separated groups of exactly 3 digits are
    changed; a number with one dot may be a decimal and is left as it is.
    """
    return _DOT_THOUSANDS_RE.sub(lambda m: m.group(0).replace(".", ","), text)


def find_unit(text: str) -> str | None:
    """The first unit line on the page, e.g. "In thousands of tenge", or None."""
    for line in text.splitlines():
        match = _UNIT_RE.match(line.strip())
        if match:
            return match.group(0).strip()
    return None


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into pieces of at most `size` characters, overlapping by about `overlap`.

    Cuts at a line break or space when there is one in the second half of the
    window, so words and table rows are not cut in the middle.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    pieces = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        space = text.find(" ", next_start, end)  # start the overlap at a word boundary
        start = space + 1 if space != -1 else next_start
    return pieces


def table_to_markdown(table: list[list[str | None]]) -> tuple[str, str | None]:
    """Convert a pdfplumber table to markdown. Returns (markdown, problem or None).

    Empty rows and columns are dropped. Tables with fewer than 2 rows or 2
    columns, or with more than 60 % empty cells, are reported and not indexed.
    """
    rows = [[_clean_cell(c) for c in row] for row in table if row]
    rows = [r for r in rows if any(r)]
    if not rows:
        return "", "empty table"
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    rows = [[r[i] for i in keep] for r in rows]

    if len(rows) < 2 or len(keep) < 2:
        return "", f"too small ({len(rows)} rows x {len(keep)} columns), not indexed"
    cells = len(rows) * len(keep)
    empty = sum(1 for r in rows for c in r if not c)
    if empty / cells > 0.6:
        return "", f"{empty * 100 // cells}% empty cells, not indexed"

    header, body = rows[0], rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
        *("| " + " | ".join(r) + " |" for r in body),
    ]
    return "\n".join(lines), None


def split_table(markdown: str, max_chars: int = MAX_TABLE_CHARS) -> list[str]:
    """Split a long markdown table by rows; every part repeats the header."""
    if len(markdown) <= max_chars:
        return [markdown]
    lines = markdown.split("\n")
    header, body = lines[:2], lines[2:]
    parts: list[str] = []
    current: list[str] = []
    for line in body:
        if current and len("\n".join(header + current + [line])) > max_chars:
            parts.append("\n".join(header + current))
            current = []
        current.append(line)
    if current:
        parts.append("\n".join(header + current))
    return parts


def _clean_cell(cell: str | None) -> str:
    return normalize_numbers(" ".join((cell or "").split())).replace("|", "\\|")
