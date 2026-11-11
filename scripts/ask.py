"""Ask the agent one question from the terminal.

    python -m scripts.ask "How did Halyk Bank's net income change from 2022 to 2023?"
"""

from __future__ import annotations

import sys

from src.agent.agent import answer
from src.agent.llm import LLMConfigError


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('Usage: python -m scripts.ask "your question"')
        return 2
    question = " ".join(argv[1:])

    try:
        result = answer(question)
    except LLMConfigError as exc:
        print(f"Configuration error: {exc}")
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
