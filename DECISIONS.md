# DECISIONS.md

Important decisions, including where the agent was wrong and how we noticed.

## 2026-11-11 · Agent layer (Berikzhan)

### Citations only from chunks the retriever returned
The LLM marks each figure with a chunk id like `[halyk-2023-p87-0]`. `agent.py` keeps only ids
that `search_reports` actually returned and drops any other id, so the model cannot invent a page.

### The agent recommended a broken model (agent was wrong)
Claude Code picked `nvidia/nemotron-3-ultra-550b-a55b:free` from the OpenRouter model list
by its description only, without testing it. `scripts/ask.py` then printed an empty answer.
**How we noticed:** `ask.py -v` showed "empty reply from the model"; a raw API call showed that
even "Say hello" returned `content: null` and garbage text in the `reasoning` field.
**Fix:** switched models. `google/gemma-4-31b-it:free` gave HTTP 429 (free tier overloaded).
We now use `baidu/ernie-5.5-flash-preview:free`. It is a preview model and may be removed,
so the model is configured only in `.env` (`LLM_MODEL`) and can be changed without code changes.

### Empty model replies were shown as an empty answer (bug in our code)
The first version of `agent.py` treated a reply with no text and no tool calls as a final
answer, so the user saw a blank line. **Fix:** the agent asks the model once more; if the
reply is still empty it returns `found=False` with a clear message. Added `-v` to
`scripts/ask.py` to print every tool call, and two tests for this case.

### API key pasted into the agent chat (our mistake)
An OpenRouter key was pasted into the Claude Code chat by accident. The agent warned about it.
**Fix:** the key was deleted on OpenRouter and a new one created; the key was removed from the
exported agent log before committing. Keys go only into `.env`.

### Commit author stays the student, not the agent
A hook in the agent environment asked to rewrite commits with the author "Claude". We refused:
the course grades each member by their own commits, so commits are authored by AdamNarxoz.

### Manual check with stub data (model: baidu/ernie-5.5-flash-preview:free)
| Question | Result |
|---|---|
| Halyk net income change 2022→2023 | 17.31% via `percent_change`, cites p. 79 and p. 87 ✅ |
| Halyk debt-to-equity 2023 | 5.8 via `debt_to_equity`, cites p. 85 ✅ |
| Kcell net income 2023 (not in stub) | "Not found in the reports", no figures ✅ |
