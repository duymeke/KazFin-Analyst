"""Streamlit UI for KazFin Analyst.

    streamlit run src/app/streamlit_app.py
    USE_FAKE_AGENT=1 streamlit run src/app/streamlit_app.py   # offline demo
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit puts only this file's folder on sys.path; add the repo root so
# that `import src...` works.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.app.backend import ask, choose_answer_fn, format_citation  # noqa: E402

st.set_page_config(page_title="KazFin Analyst", page_icon="📊")
st.title("KazFin Analyst")
st.write(
    "Ask a question about the annual reports of companies listed on KASE. "
    "The assistant finds the figures in the reports, computes ratios with "
    "calculator tools and cites the company, year and page for every figure."
)

backend = choose_answer_fn()
if backend.is_fake:
    st.info(f"Demo mode: answers are FAKE ({backend.reason}).")

with st.form("question_form"):
    question = st.text_input(
        "Question",
        placeholder="How did Halyk Bank's net income change from 2022 to 2023?",
    )
    submitted = st.form_submit_button("Ask")

if submitted:
    if not question.strip():
        st.warning("Please type a question.")
        st.stop()

    with st.spinner("Searching the reports..."):
        result = ask(backend.answer_fn, question.strip())

    if result.error:
        st.error(result.error)
        st.stop()

    answer = result.answer
    if not answer.found:
        st.warning("Not found in the reports. The assistant did not find this data in the annual reports.")
        st.caption(answer.text)
        st.stop()

    st.subheader("Answer")
    st.write(answer.text)

    if answer.citations:
        st.subheader("Sources")
        for c in answer.citations:
            with st.expander(format_citation(c)):
                st.caption(c.source_file)
                st.write(c.snippet or "(no snippet)")
    else:
        st.caption("No sources were cited.")

    if answer.numbers:
        st.caption("Key numbers: " + ", ".join(f"{n:g}" for n in answer.numbers))
