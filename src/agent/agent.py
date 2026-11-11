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
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.agent.llm import chat
from src.agent.stub_retriever import StubRetriever
from src.agent.tools import CALCULATORS, TOOL_SCHEMAS
from src.models import Answer, Chunk, Citation

MAX_STEPS = 6
NOT_FOUND = "Not found in the reports"

SYSTEM_PROMPT = f"""You are KazFin Analyst, an assistant that answers questions about the annual reports of companies listed on the Kazakhstan Stock Exchange (KASE).

Rules:
1. Always call search_reports to find figures. Use only figures that appear in the returned chunks. Never use your own knowledge for figures.
2. Never do arithmetic yourself. For any growth, change, ratio, margin, ROE or debt-to-equity, call the calculator tool and use its result.
3. Cite every figure you use by putting the chunk id in square brackets right after it, e.g. "Net income was 610,000 million KZT [halyk-2023-p87-0]". Use only ids returned by search_reports.
4. If the needed figures are not in the returned chunks, after at most two searches reply exactly: "{NOT_FOUND}." followed by one short sentence on what is missing. Do not guess.
5. Keep the answer short: the result first, then the figures it is based on, with units (e.g. million KZT, %).
"""

_CITE_RE = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
_NUMBER_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
_PAGE_RE = re.compile(r"\b(?:p\.|page|pages)\s*\d+", re.IGNORECASE)


def answer(question: str, retriever: Any = None) -> Answer:
    """Answer one question about the reports. `retriever` defaults to StubRetriever."""
    retriever = retriever if retriever is not None else StubRetriever()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    seen_chunks: dict[str, Chunk] = {}
    computed: list[float] = []

    for _ in range(MAX_STEPS):
        reply = chat(messages, tools=TOOL_SCHEMAS)
        tool_calls = getattr(reply, "tool_calls", None) or []
        if not tool_calls:
            return _build_answer(reply.content or "", seen_chunks, computed)

        messages.append(_assistant_message(reply, tool_calls))
        for call in tool_calls:
            result = _run_tool(call.function.name, call.function.arguments, retriever, seen_chunks, computed)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    return Answer(
        text=f"{NOT_FOUND}: the assistant could not finish within {MAX_STEPS} steps.",
        found=False,
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
    numbers = list(dict.fromkeys(computed + _numbers_in_text(without_markers)))
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
    """Figures written in the answer, skipping years (2000-2100) and page numbers."""
    text = _PAGE_RE.sub("", text)
    numbers = []
    for token in _NUMBER_RE.findall(text):
        value = float(token.replace(",", ""))
        if "." not in token and "," not in token and 2000 <= value <= 2100:
            continue
        numbers.append(value)
    return numbers
