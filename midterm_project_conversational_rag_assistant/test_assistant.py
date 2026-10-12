"""Offline tests (pytest -q). Ollama is replaced by a scripted fake model and a word-count embedding, so they check
loading, indexing, retrieval, follow-up handling and memory, but not the quality of a real model's answers."""
import re
import zlib

import pandas as pd
import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import assistant as A

# Test fixtures and fake model components.
# These lightweight stand-ins mimic the embedding and LLM interfaces so the tests
# can validate retrieval and memory logic without requiring a live Ollama server.
PDF, XLSX = "data/handbook.pdf", "data/sales.xlsx"


class WordEmbeddings(Embeddings):  # deterministic stand-in: similar words -> similar vectors
    def embed_query(self, text):
        v = [0.0] * 512
        for w in re.findall(r"\w+", text.lower()):
            v[zlib.crc32(w.encode()) % 512] += 1
        n = sum(x * x for x in v) ** 0.5 or 1
        return [x / n for x in v]

    def embed_documents(self, texts):
        return [self.embed_query(t) for t in texts]


class FakeLLM:
    """Records every prompt. Condense prompts get 'STANDALONE: <last message>', summary prompts get 'SUMMARY n'."""

    def __init__(self):
        self.prompts, self.runnable = [], RunnableLambda(self._run)

    def _run(self, prompt):
        msgs = prompt.to_messages()
        self.prompts.append(msgs)
        text = msgs[0].content
        if text.startswith("Given the chat history"):
            return AIMessage("STANDALONE: " + msgs[-1].content)
        if text.startswith("Update this conversation summary"):
            return AIMessage(f"SUMMARY {sum(len(p) for p in self.prompts) % 997}")
        return AIMessage("ANSWER to " + msgs[-1].content)

    def kinds(self):
        return ["condense" if p[0].content.startswith("Given") else "summary" if p[0].content.startswith("Update") else "answer" for p in self.prompts]


# Convenience constructor for tests.
# It builds the assistant with a deterministic fake LLM and token embedding so each
# assertion can reason about prompts and retrieval behavior instead of model output.
def bot(sources=(PDF, XLSX), **kw):
    fake = FakeLLM()
    b = A.Assistant(list(sources), llm=fake.runnable, embeddings=WordEmbeddings(), **kw)
    return b, fake


# ---------------------------------------------------------------- data integration
def test_sheet_url_conversion():
    link = "https://docs.google.com/spreadsheets/d/1AbC-dEf_9/edit?usp=sharing&gid=123#gid=123"
    assert A.sheet_url(link) == "https://docs.google.com/spreadsheets/d/1AbC-dEf_9/export?format=csv&gid=123"
    assert A.sheet_url("https://docs.google.com/spreadsheets/d/XYZ/edit").endswith("/XYZ/export?format=csv&gid=0")
    assert A.sheet_url("data/x.csv") == "data/x.csv"


def test_excel_rows_and_summary():
    rows, summ = A.load_sheet(XLSX)
    assert len(rows) == 44 and len(summ) == 2  # 40 sales rows + 4 target rows; one summary per sheet
    assert rows[0].page_content.startswith("Sales | Date: 2026-07-01; Region:") and rows[0].metadata == {"source": "sales.xlsx", "sheet": "Sales", "row": 2}
    s = next(d.page_content for d in summ if "'Sales'" in d.page_content)
    assert "40 rows" in s and "Total Revenue in sheet 'Sales': 221840." in s
    assert "Revenue by Region in sheet 'Sales': East 10700, North 91840, South 40210, West 79090. Highest: North. Lowest: East." in s
    assert "transactions (rows) by Region in sheet 'Sales': East 3, North 12, South 11, West 14." in s


def test_google_sheet_is_fetched_through_the_export_link(monkeypatch):
    seen = []
    monkeypatch.setattr(pd, "read_csv", lambda url: seen.append(url) or pd.DataFrame({"Item": ["a", "b", "c"], "Cost": [1, 2, 3]}))
    rows, summ = A.load_sheet("https://docs.google.com/spreadsheets/d/SHEET1/edit?gid=5")
    assert seen == ["https://docs.google.com/spreadsheets/d/SHEET1/export?format=csv&gid=5"]
    assert rows[1].page_content == "Sheet1 | Item: b; Cost: 2" and A.cite(rows[1]) == "Google Sheet Sheet1 row 3" and "6" in summ[0].page_content


def test_unreadable_sheet_gives_a_helpful_error(monkeypatch):
    def denied(url):
        raise OSError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(pd, "read_csv", denied)
    with pytest.raises(ValueError, match="Anyone with the link"):
        A.load_sheet("https://docs.google.com/spreadsheets/d/PRIVATE/edit")


def test_csv_file(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("City,Sales\nCairo,10\nGiza,20\n")
    rows, summ = A.load_sheet(str(p))
    assert [r.page_content for r in rows] == ["Sheet1 | City: Cairo; Sales: 10", "Sheet1 | City: Giza; Sales: 20"]


# ---------------------------------------------------------------- embedding, indexing, retrieval
# These tests verify that PDFs and spreadsheet rows are split into retrievable
# chunks and that citations point back to the correct page or sheet row.
def test_pdf_chunks_are_indexed_and_searchable_with_page_citations():
    b, _ = bot([PDF], k=2)
    top = b.retriever.invoke("How many days of annual leave?")
    assert "21 days" in top[0].page_content and A.cite(top[0]) == "data/handbook.pdf p.1"


def test_sheet_rows_are_searchable():
    b, _ = bot([XLSX], k=3)
    assert any("Q3 Revenue Target: 22000" in d.page_content for d in b.retriever.invoke("Region: West Q3 Revenue Target"))


# ---------------------------------------------------------------- question answering and memory
# These assertions ensure the system includes prior chat summary and retrieved
# document context inside the answer prompt and that follow-up questions are handled
# with the right memory behavior.
def test_answer_prompt_contains_summaries_and_retrieved_context():
    b, fake = bot()
    reply, docs = b.ask("How many days of annual leave?")

    # No history means no condense step.
    assert reply == "ANSWER to How many days of annual leave?"
    assert fake.kinds() == ["answer"]

    system = fake.prompts[0][0].content

    # Verify the conversation summary is included.
    assert "Conversation summary:" in system
    assert "none" in system

    # Verify document summaries and retrieved context are included.
    assert "Summary of sheet 'Sales'" in system
    assert "21 days" in system
    assert any("Summary of sheet" in d.page_content for d in docs)



def test_follow_up_is_rewritten_and_history_is_sent():
    b, fake = bot()
    b.ask("How many days of annual leave?")
    b.ask("And sick leave?")
    assert fake.kinds() == ["answer", "condense", "answer"]
    condense = fake.prompts[1]
    assert [m.content for m in condense[1:]] == ["How many days of annual leave?", "ANSWER to How many days of annual leave?", "And sick leave?"]
    final = fake.prompts[2]
    assert [m.type for m in final[1:]] == ["human", "ai", "human"] and final[1].content == "How many days of annual leave?"
    assert "Sick leave is separate" in final[0].content  # retrieval used the rewritten question ("STANDALONE: And sick leave?")


def test_buffer_memory_keeps_everything():
    b, _ = bot([PDF])
    for i in range(6):
        b.ask(f"question {i} about leave")
    assert len(b.history) == 12 and b.history[0].content == "question 0 about leave" and b.summary == ""



def test_summary_memory_folds_old_turns_into_a_summary():
    b, fake = bot([PDF], max_turns=2)

    for i in range(4):
        b.ask(f"question {i} about leave")

    # Keep the last 2 turns verbatim.
    assert [m.content for m in b.history[::2]] == [
        "question 2 about leave",
        "question 3 about leave",
    ]

    assert b.summary.startswith("SUMMARY")
    assert fake.kinds().count("summary") == 2

    last_summary_prompt = [
        p for p in fake.prompts
        if p[0].content.startswith("Update")
    ][-1][0].content

    assert "human: question 1 about leave" in last_summary_prompt

    b.ask("question 4 about leave")

    # The answer prompt should contain the existing conversation summary.
    answer_prompt = fake.prompts[-2][0].content
    assert "Conversation summary:" in answer_prompt
    assert "SUMMARY" in answer_prompt


# ---------------------------------------------------------------- evaluation script
# This checks that the evaluation benchmark itself treats expected answers and
# not-found phrases correctly when comparing strings.
def test_evaluation_scoring():
    import evaluate

    class Echo:
        def reset(self):
            pass

        def ask(self, q):
            return {"annual": "You get 21 days", "carry": "up to 5", "CEO": "I could not find that"}.get(next((k for k in ("annual", "carry", "CEO") if k in q), ""), "no idea"), []

    assert evaluate.matches("The total is 221,840 USD", ["221840"]) and not evaluate.matches("about 20", ["21"])
    assert evaluate.matches("I couldn't find it", evaluate.NOT_FOUND)
    ok, hit = evaluate.run_single(Echo(), [("annual leave?", ["21"]), ("something else", ["x"])])
    assert ok == [True, False]