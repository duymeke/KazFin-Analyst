"""Add an OCR text layer to every PDF in data/reports.json.

    python -m scripts.ocr_reports            # OCR files not done yet
    python -m scripts.ocr_reports --force    # redo all files

Runs `ocrmypdf --skip-text -l eng --output-type pdf data/raw/<file> data/ocr/<file>`.
--skip-text OCRs only pages without a text layer; pages with text are kept as
they are, and the page order does not change, so page numbers and citations
still match the original PDF. build_index reads data/ocr/<file> when it exists.

Needs ocrmypdf, Tesseract (English) and Ghostscript:
macOS `brew install ocrmypdf`, Debian/Ubuntu `sudo apt install ocrmypdf`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pymupdf

from src.ingest.manifest import DEFAULT_MANIFEST, DEFAULT_OCR_DIR, DEFAULT_RAW_DIR, load_manifest


def empty_pages(path: str | Path) -> list[int]:
    """1-based numbers of pages that have no extractable text."""
    with pymupdf.open(path) as doc:
        return [i + 1 for i, page in enumerate(doc) if not page.get_text().strip()]


INVALID_OUTPUT = 4  # ocrmypdf exit code: output written, but qpdf found errors in it


def check_pages(src: str | Path, ocr: str | Path) -> str | None:
    """Why the OCR copy cannot replace the source, or None if it can.

    It must have the same number of pages, and every page that has text in the
    source must have the same text in the copy (--skip-text leaves those pages alone).
    """
    with pymupdf.open(src) as a, pymupdf.open(ocr) as b:
        if len(a) != len(b):
            return f"{len(b)} pages instead of {len(a)}"
        for i, (pa, pb) in enumerate(zip(a, b), start=1):
            text = pa.get_text()
            if text.strip() and pb.get_text() != text:
                return f"text of page {i} changed"
    return None


def ocr_command(src: Path, dst: Path, jobs: int | None = None) -> list[str]:
    """The ocrmypdf command line for one file."""
    cmd = ["ocrmypdf", "--skip-text", "-l", "eng", "--output-type", "pdf", "--quiet"]
    if jobs:
        cmd += ["--jobs", str(jobs)]
    return cmd + [str(src), str(dst)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--ocr-dir", default=DEFAULT_OCR_DIR)
    parser.add_argument("--force", action="store_true", help="redo files that are already done")
    parser.add_argument("--jobs", type=int, default=None, help="CPU cores for ocrmypdf")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # show progress per file, also when piped

    if shutil.which("ocrmypdf") is None:
        print("ocrmypdf not found. Install it: macOS `brew install ocrmypdf`, "
              "Debian/Ubuntu `sudo apt install ocrmypdf`.")
        return 1

    ocr_dir = Path(args.ocr_dir)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    # skipped manifest entries are OCRed too, so the file is ready when the skip is removed
    for entry in load_manifest(args.manifest).reports:
        src = Path(args.raw_dir) / entry.file
        dst = ocr_dir / entry.file
        if not src.exists():
            print(f"{entry.file:<16} MISSING: {src}")
            failed += 1
            continue
        if dst.exists() and not args.force:
            print(f"{entry.file:<16} already done (use --force to redo)")
            continue

        before = empty_pages(src)
        start = time.perf_counter()
        tmp = dst.with_suffix(".tmp.pdf")  # a crash never leaves a half-written OCR file
        proc = subprocess.run(ocr_command(src, tmp, args.jobs), capture_output=True, text=True)
        seconds = time.perf_counter() - start
        warning = None
        if proc.returncode == INVALID_OUTPUT and tmp.exists():
            # ocrmypdf wrote the file but qpdf found structure errors (e.g. halyk_2024:
            # bad "0 0 R" references). Keep it only if no page or text was lost.
            problem = check_pages(src, tmp)
            if problem is None:
                warning = ("ocrmypdf reported structure errors in the output PDF (exit code 4); "
                           "page count and text checked, kept")
            else:
                print(f"{entry.file:<16} FAILED (ocrmypdf exit code 4: {problem})")
                tmp.unlink(missing_ok=True)
                failed += 1
                continue
        elif proc.returncode != 0:
            tmp.unlink(missing_ok=True)
            print(f"{entry.file:<16} FAILED (ocrmypdf exit code {proc.returncode})")
            print("      " + (proc.stderr.strip().splitlines() or ["no error output"])[-1])
            failed += 1
            continue
        tmp.replace(dst)

        after = empty_pages(dst)
        print(f"{entry.file:<16} OCRed {len(before) - len(after):>3} page(s), "
              f"{len(after):>3} still without text, {seconds:6.1f} s")
        if warning:
            print(f"      ! {warning}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
