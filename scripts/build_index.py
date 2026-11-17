"""Parse all PDFs listed in data/reports.json and rebuild the vector index.

    python -m scripts.build_index

Reads data/ocr/<file> (made by scripts/ocr_reports.py) when it exists,
otherwise data/raw/<file>. Chunks always keep the original file name and page
numbers, so citations point to the original PDF.

Prints per file: pages, text and table chunks, pages where no table was
detected, and every parsing problem (scanned pages, broken tables), so bad
PDFs are visible instead of silently producing an empty index.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

from src.ingest.index import DEFAULT_INDEX_DIR, write_index
from src.ingest.manifest import (
    DEFAULT_MANIFEST,
    DEFAULT_OCR_DIR,
    DEFAULT_RAW_DIR,
    load_manifest,
    source_path,
)
from src.ingest.ocr_fixes import DEFAULT_OCR_FIXES, load_ocr_fixes
from src.ingest.pdf_parser import ParseResult, parse_pdf_with_report
from src.models import Chunk


def _ranges(pages: list[int]) -> str:
    """[3, 4, 5, 9] -> "3-5, 9"."""
    out: list[str] = []
    for p in sorted(set(pages)):
        if out and int(out[-1].split("-")[-1]) == p - 1:
            out[-1] = f"{out[-1].split('-')[0]}-{p}"
        else:
            out.append(str(p))
    return ", ".join(out)


def _print_problems(result: ParseResult) -> None:
    by_reason: dict[str, list[int]] = {}
    for page, reason in result.problems:
        by_reason.setdefault(reason, []).append(page)
    for reason, pages in by_reason.items():
        print(f"      ! {reason}: page(s) {_ranges(pages)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--ocr-dir", default=DEFAULT_OCR_DIR)
    parser.add_argument("--no-ocr", action="store_true", help="ignore data/ocr/, parse raw PDFs")
    parser.add_argument("--ocr-fixes", default=DEFAULT_OCR_FIXES)
    parser.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)
    args = parser.parse_args(argv)
    started = time.perf_counter()

    manifest = load_manifest(args.manifest)
    ocr_fixes = load_ocr_fixes(args.ocr_fixes)
    all_chunks: list[Chunk] = []
    text_hashes: dict[str, str] = {}

    header = (
        f"{'file':<16} {'pages':>5} {'text':>6} {'table':>6} {'total':>6} "
        f"{'no-table pages':>15}  source"
    )
    print(header)
    print("-" * len(header))
    for entry in manifest.reports:
        path = source_path(entry.file, args.raw_dir, None if args.no_ocr else args.ocr_dir)
        if entry.skip:
            print(f"{entry.file:<16} SKIPPED: {entry.skip}")
            continue
        if not path.exists():
            print(f"{entry.file:<16} MISSING: {path}")
            continue

        # fixes are written for the OCR text, so they apply only to the OCR copy
        is_ocr_copy = not args.no_ocr and path.parent.resolve() == Path(args.ocr_dir).resolve()
        fixes = ocr_fixes.get(entry.file, []) if is_ocr_copy else []
        result = parse_pdf_with_report(
            path, entry.company, entry.year, source_name=entry.file, fixes=fixes
        )
        n_text = sum(1 for c in result.chunks if c.kind == "text")
        n_table = len(result.chunks) - n_text
        print(
            f"{entry.file:<16} {result.page_count:>5} {n_text:>6} {n_table:>6} "
            f"{len(result.chunks):>6} {result.pages_without_tables:>15}  {path.parent.name}/"
        )
        if result.fixes_applied:
            print(f"      OCR fixes applied: {result.fixes_applied} of {len(fixes)}")
        _print_problems(result)

        digest = hashlib.sha256("".join(c.text for c in result.chunks).encode()).hexdigest()
        if digest in text_hashes:
            print(f"      ! same text as {text_hashes[digest]}: probably a duplicate file")
        text_hashes[digest] = entry.file
        all_chunks.extend(result.chunks)

    if not all_chunks:
        print("No chunks parsed; index not written.")
        return 1
    stored = write_index(all_chunks, args.index_dir)
    n_table = sum(1 for c in all_chunks if c.kind == "table")
    print("-" * len(header))
    print(
        f"Stored {stored} chunks ({stored - n_table} text, {n_table} table) "
        f"in {args.index_dir} in {time.perf_counter() - started:.1f} s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
