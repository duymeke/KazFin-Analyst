"""The agent: answers one question about the annual reports with a tool-calling loop.

Flow for one question:
1. Send the question to the LLM together with TOOL_SCHEMAS.
2. While the LLM asks for tools (max MAX_STEPS rounds), run them:
   - search_reports -> retriever.search(), chunks go back to the LLM as JSON
   - calculators    -> functions from tools.py, the result goes back as JSON
3. When the LLM replies with plain text, turn it into an Answer:
   - citations: only chunks the retriever really returned and the LLM cited
     with [chunk_id]; ids the LLM made up are dropped
   - numbers: calculator results first, then figures written in the text
   - found=False if the LLM said "Not found in the reports"

Guards in code, because the model does not always follow the prompt:
- a final answer before any search_reports call is sent back once; a second
  one gives found=False (the model answered from its own knowledge)
- a final answer that cites chunk ids search never returned is sent back once
- figures with no valid citation give found=False instead of an unsourced answer
- after MAX_SEARCHES searches, search_reports returns an error to the model
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.agent.llm import chat
from src.agent.tools import CALCULATORS, TOOL_SCHEMAS
from src.models import Answer, Chunk, Citation

MAX_STEPS = 10  # up to MAX_SEARCHES searches, a calculator, two nudges and the answer
MAX_SEARCHES = 4
INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "index"
INDEX_MISSING = "Index not found. Run: python -m scripts.build_index"
NOT_FOUND = "Not found in the reports"
EMPTY_REPLY_NUDGE = "Your last reply was empty. Give your final answer now, following the rules."
NO_SEARCH_NUDGE = (
    "You answered without calling search_reports. Never use your own knowledge for figures: "
    f'call search_reports now, or reply exactly "{NOT_FOUND}."'
)
SEARCH_LIMIT_ERROR = (
    f"search limit reached ({MAX_SEARCHES} searches). Answer from the chunks you already have, "
    f'or reply "{NOT_FOUND}."'
)
NO_SEARCH_ANSWER = f"{NOT_FOUND}: the model answered without searching the reports."
NO_SOURCE_ANSWER = f"{NOT_FOUND}: the answer had figures but no source in the reports."

log = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are KazFin Analyst, an assistant that answers questions about the audited IFRS financial statements of companies listed on the Kazakhstan Stock Exchange (KASE). The reports available are for Halyk Bank, KEGOC and Kcell.

Rules:
1. Always call search_reports to find figures, and always pass company=. Use only figures that appear in the returned chunks. Never use your own knowledge for figures. If the company asked about is not Halyk Bank, KEGOC or Kcell, reply "{NOT_FOUND}." without guessing.
2. Never do arithmetic yourself. For any growth, change, ratio, margin, ROE or debt-to-equity, call the calculator tool and use its result.
3. Units: a chunk may start with "Units: ..." (e.g. "In thousands of tenge", "In millions of tenge"), or the unit is written in the chunk text. KEGOC reports in thousands of tenge, Halyk Bank and Kcell in millions of tenge. Check the unit of every figure, always state the unit in the answer, and pass figures in the same unit to a calculator.
4. Years and columns: the report for year X has a column for year X and a comparative column for year X-1. For a figure for year Y, search year=Y first. If it is not there, search year=Y+1 and take its comparative (Y) column. Always take the column of the year asked, never the neighbouring one, and say which report the figure came from.
5. Prefer the main statements (statement of profit or loss, statement of financial position) over the notes when both have the figure. Some statement pages were read by OCR and can have wrong digits; if a row has no label or its numbers look inconsistent, use the same figure from another page (e.g. the statement of changes in equity) and say so.
6. Cite every figure you use by putting the chunk id in square brackets right after it, e.g. "Net income was 610,000 million KZT [halyk-2023-p87-0]". Use only ids returned by search_reports.
7. If the needed figures are not in the returned chunks after at most three searches, reply exactly: "{NOT_FOUND}." followed by one short sentence on what is missing. Do not guess.
8. Keep the answer short: the result first, then the figures it is based on, with units (e.g. million KZT, %). Write numbers with commas as thousands separators (1,097,066,105).
"""

_CITE_RE = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
_NUMBER_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
_PAGE_RE = re.compile(r"\b(?:p\.|page|pages)\s*\d+", re.IGNORECASE)
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
# "31 December" and "December 31": the day is not a figure (the year is skipped below)
_DATE_RE = re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\b|\b(?:{_MONTHS})\s+\d{{1,2}}\b(?!\d)")
# 1.097.066.105: two or more dot groups of 3 digits. One dot (17.31, 569.653)
# stays a decimal, because it cannot be told apart from a thousands separator.
_DOT_THOUSANDS_RE = re.compile(r"(?<![\d.,])-?\d{1,3}(?:\.\d{3}){2,}(?![\d.])")
# 693 435 or 1 097 066 105 (also with no-break or narrow no-break spaces)
_SPACE_THOUSANDS_RE = re.compile(r"(?<![\d.,])-?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")


@lru_cache(maxsize=1)
def _default_retriever() -> Any:
    """The real Retriever over data/index, opened once per process.

    Imported here, not at the top, so this module still imports without chromadb
    (the UI falls back to the fake agent only if this import fails).
    """
    if not INDEX_DIR.exists():
        raise FileNotFoundError(INDEX_MISSING)
    from src.ingest.retriever import Retriever

    return Retriever(index_dir=INDEX_DIR)


def answer(question: str, retriever: Any = None) -> Answer:
    """Answer one question about the reports.

    `retriever` defaults to the real Retriever over data/index; tests and eval
    can pass a stub with the same search() interface.
    """
    retriever = retriever if retriever is not None else _default_retriever()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    seen_chunks: dict[str, Chunk] = {}
    computed: list[float] = []
    searches = [0]  # a list so _run_tool can count searches

    nudged = False
    nudged_search = False
    nudged_citations = False

    for step in range(1, MAX_STEPS + 1):
        reply = chat(messages, tools=TOOL_SCHEMAS)
        tool_calls = getattr(reply, "tool_calls", None) or []
        content = (reply.content or "").strip()

        if not tool_calls:
            if content:
                log.info("step %d: final answer: %s", step, content)
                not_found = NOT_FOUND.lower() in content.lower()
                if not not_found and searches[0] == 0:
                    if nudged_search:
                        log.info("step %d: answered twice without searching", step)
                        return Answer(text=NO_SEARCH_ANSWER, found=False)
                    log.info("step %d: no search before the answer, asking to search", step)
                    nudged_search = True
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": NO_SEARCH_NUDGE})
                    continue
                invented = [i for i in dict.fromkeys(_CITE_RE.findall(content)) if i not in seen_chunks]
                if not not_found and invented and not nudged_citations:
                    log.info("step %d: cited ids search never returned: %s", step, invented)
                    nudged_citations = True
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": _citation_nudge(invented)})
                    continue
                return _build_answer(content, seen_chunks, computed)
            # Some models (often reasoning ones) return neither text nor tool
            # calls. Ask once more instead of returning an empty answer.
            log.info("step %d: empty reply from the model", step)
            if nudged:
                break
            nudged = True
            messages.append({"role": "user", "content": EMPTY_REPLY_NUDGE})
            continue

        messages.append(_assistant_message(reply, tool_calls))
        for call in tool_calls:
            log.info("step %d: call %s(%s)", step, call.function.name, call.function.arguments)
            result = _run_tool(
                call.function.name, call.function.arguments, retriever, seen_chunks, computed, searches
            )
            log.info("step %d: result %s", step, result if len(result) <= 500 else result[:500] + "...")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    else:
        return Answer(
            text=f"{NOT_FOUND}: the assistant could not finish within {MAX_STEPS} steps.",
            found=False,
        )

    return Answer(
        text=f"{NOT_FOUND}: the model returned an empty answer. Try again or use another model.",
        found=False,
    )


def _citation_nudge(invented: list[str]) -> str:
    """Message sent back when the answer cites ids that search_reports never returned."""
    return (
        f"These ids were never returned by search_reports: {', '.join(invented)}. "
        "Cite only ids from the search results. If a figure is not in them, search again "
        f'or reply "{NOT_FOUND}."'
    )


def _assistant_message(reply: Any, tool_calls: list[Any]) -> dict[str, Any]:
    """Convert the SDK reply into a plain dict so it can be sent back to the API."""
    return {
        "role": "assistant",
        "content": reply.content or "",
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.function.name, "arguments": c.function.arguments},
            }
            for c in tool_calls
        ],
    }


def _run_tool(
    name: str,
    raw_args: str,
    retriever: Any,
    seen_chunks: dict[str, Chunk],
    computed: list[float],
    searches: list[int] | None = None,
) -> str:
    """Execute one tool call and return its result as a JSON string for the LLM.

    Errors (bad JSON, unknown tool, zero denominator) are returned to the LLM
    as {"error": ...} instead of crashing the loop.
    """
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "arguments are not valid JSON"})

    if name == "search_reports":
        if searches is not None:
            if searches[0] >= MAX_SEARCHES:
                return json.dumps({"error": SEARCH_LIMIT_ERROR})
            searches[0] += 1
        try:
            chunks = retriever.search(
                args.get("query", ""),
                k=5,
                company=args.get("company"),
                year=args.get("year"),
            )
        except Exception as exc:  # retriever failure should not kill the answer
            return json.dumps({"error": f"search failed: {exc}"})
        for c in chunks:
            seen_chunks[c.id] = c
        return json.dumps(
            [
                {"id": c.id, "company": c.company, "year": c.year, "page": c.page, "text": c.text}
                for c in chunks
            ],
            ensure_ascii=False,
        )

    func = CALCULATORS.get(name)
    if func is None:
        return json.dumps({"error": f"unknown tool: {name}"})
    try:
        value = func(**args)
    except (ValueError, TypeError) as exc:
        return json.dumps({"error": str(exc)})
    computed.append(value)
    return json.dumps({"result": value})


def _build_answer(text: str, seen_chunks: dict[str, Chunk], computed: list[float]) -> Answer:
    """Turn the LLM's final text into an Answer with verified citations."""
    if NOT_FOUND.lower() in text.lower():
        return Answer(text=_CITE_RE.sub("", text).strip(), found=False)

    cited_ids = [i for i in dict.fromkeys(_CITE_RE.findall(text)) if i in seen_chunks]
    citations = [_to_citation(seen_chunks[i]) for i in cited_ids]

    def replace(match: re.Match[str]) -> str:
        chunk = seen_chunks.get(match.group(1))
        if chunk is None:
            return ""  # the LLM cited a chunk it never received: drop it
        return f"({chunk.company} {chunk.year}, p. {chunk.page})"

    without_markers = _CITE_RE.sub("", text)
    figures = _numbers_in_text(without_markers)
    if not citations and (figures or computed):
        # figures the reader cannot check against a page are not an answer
        return Answer(text=NO_SOURCE_ANSWER, found=False)
    numbers = list(dict.fromkeys(computed + figures))
    clean_text = re.sub(r"[ \t]+([.,;])", r"\1", _CITE_RE.sub(replace, text)).strip()
    return Answer(text=clean_text, citations=citations, numbers=numbers)


def _to_citation(chunk: Chunk) -> Citation:
    snippet = chunk.text if len(chunk.text) <= 300 else chunk.text[:297] + "..."
    return Citation(
        company=chunk.company,
        year=chunk.year,
        source_file=chunk.source_file,
        page=chunk.page,
        snippet=snippet,
    )


def _numbers_in_text(text: str) -> list[float]:
    """Figures written in the answer, skipping years (2000-2100) and page numbers.

    Thousands separators may be commas (1,097,066,105), spaces (693 435) or
    dots when there are at least two of them (1.097.066.105).
    """
    text = _PAGE_RE.sub("", text)
    text = _DATE_RE.sub("", text)
    text = _DOT_THOUSANDS_RE.sub(lambda m: m.group().replace(".", ","), text)
    text = _SPACE_THOUSANDS_RE.sub(lambda m: re.sub(r"[ \u00a0\u202f]", ",", m.group()), text)
    numbers = []
    for token in _NUMBER_RE.findall(text):
        value = float(token.replace(",", ""))
        if "." not in token and "," not in token and 2000 <= value <= 2100:
            continue
        numbers.append(value)
    return numbers
