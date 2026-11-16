"""Search the report index from the command line.

    python -m scripts.search "net income" --company Halyk --year 2023 -k 5
"""

from __future__ import annotations

import argparse
import sys

from src.ingest.retriever import Retriever


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search the annual report index.")
    parser.add_argument("query")
    parser.add_argument("--company", default=None, help='e.g. "Halyk", "KEGOC", "Kcell"')
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("-k", type=int, default=5, help="number of results (default 5)")
    parser.add_argument("--chars", type=int, default=300, help="characters of text to show")
    args = parser.parse_args(argv)

    try:
        chunks = Retriever().search(args.query, k=args.k, company=args.company, year=args.year)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    if not chunks:
        print("No results (unknown company or year, or empty index).")
        return 0

    for rank, c in enumerate(chunks, start=1):
        print(f"{rank}. score {c.score:.3f}  page {c.page:<4} {c.kind:<5}  {c.company} {c.year}  "
              f"{c.source_file}  [{c.id}]")
        snippet = " ".join(c.text.split())
        print(f"   {snippet[: args.chars]}{'...' if len(snippet) > args.chars else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
