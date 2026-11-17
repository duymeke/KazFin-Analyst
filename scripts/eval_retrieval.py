"""Measure how high the search ranks the pages that hold the answer.

    python -m scripts.eval_retrieval            # current search
    python -m scripts.eval_retrieval -v         # also one line per query

Cases are in data/retrieval_cases.json: a query, company, year, the value of
the figure (checked by hand against the page image), the main statement page
it was taken from, and every page where the value occurs. For each case the
rank of the first result on a target page is taken, in two ways:
- strict: only the main statement page counts,
- lenient: any page with the value counts (notes often repeat the figure).
The report gives hit@1, hit@5 and MRR (mean of 1/rank, 0 when not in the top k)
per split. "dev" cases were used to tune the search, "heldout" cases were fixed
in git before the hybrid search code and are never tuned on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.ingest.manifest import REPO_ROOT
from src.ingest.retriever import Retriever

DEFAULT_CASES = REPO_ROOT / "data" / "retrieval_cases.json"


def first_hit(pages: list[int], targets: set[int]) -> int | None:
    """1-based rank of the first page in `targets`, or None."""
    for rank, page in enumerate(pages, start=1):
        if page in targets:
            return rank
    return None


def summarize(ranks: list[int | None]) -> dict[str, float]:
    """hit@1, hit@5 and MRR for a list of ranks (None = not found)."""
    n = len(ranks) or 1
    return {
        "hit@1": sum(r == 1 for r in ranks) / n,
        "hit@5": sum(r is not None and r <= 5 for r in ranks) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("-k", type=int, default=10, help="results per query (default 10)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    retriever = Retriever()
    ranks: dict[tuple[str, str], list[int | None]] = {}
    show = lambda r: str(r) if r else f">{args.k}"  # noqa: E731
    for case in cases:
        chunks = retriever.search(case["query"], k=args.k, company=case["company"], year=case["year"])
        pages = [c.page for c in chunks]
        strict = first_hit(pages, {case["statement_page"]})
        lenient = first_hit(pages, set(case["pages"]))
        ranks.setdefault((case["split"], "strict"), []).append(strict)
        ranks.setdefault((case["split"], "lenient"), []).append(lenient)
        if args.verbose:
            label = f"{case['company']} {case['year']}: {case['query']}"
            print(f"{case['split']:<8} {label[:55]:<55} strict {show(strict):>4}  lenient {show(lenient):>4}")

    if args.verbose:
        print()
    print(f"k={args.k}")
    for (split, mode), values in ranks.items():
        s = summarize(values)
        print(f"{split:<8} {mode:<8} n={len(values):<3} hit@1 {s['hit@1']:.2f}   "
              f"hit@5 {s['hit@5']:.2f}   MRR {s['mrr']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
