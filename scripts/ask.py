"""Ask the agent one question from the terminal.

    python -m scripts.ask "How did Halyk Bank's net income change from 2022 to 2023?"
    python -m scripts.ask -v "..."   # also print every tool call and result
"""

from __future__ import annotations

import logging
import sys

from src.agent.agent import answer
from src.agent.llm import LLMConfigError


def main(argv: list[str]) -> int:
    args = argv[1:]
    verbose = bool(args) and args[0] in ("-v", "--verbose")
    if verbose:
        args = args[1:]
        logging.basicConfig(level=logging.WARNING, format="  [%(name)s] %(message)s")
        logging.getLogger("src.agent.agent").setLevel(logging.INFO)
    if not args:
        print('Usage: python -m scripts.ask [-v] "your question"')
        return 2
    question = " ".join(args)

    try:
        result = answer(question)
    except LLMConfigError as exc:
        print(f"Configuration error: {exc}")
        return 1
    except Exception as exc:  # network / provider errors: short message, no stack trace
        print(f"LLM request failed: {type(exc).__name__}: {exc}")
        return 1

    print(result.text)
    print()
    if not result.found:
        print("(found: no, the data is not in the reports)")
    if result.citations:
        print("Sources:")
        for c in result.citations:
            print(f"  - {c.company}, {c.year}, {c.source_file}, page {c.page}")
    if result.numbers:
        print("Key numbers:", ", ".join(f"{n:g}" for n in result.numbers))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
