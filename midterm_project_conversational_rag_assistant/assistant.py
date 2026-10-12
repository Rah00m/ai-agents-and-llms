import argparse
import os
import re
import sys

import pandas as pd
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Prompt templates used by the assistant.
# These instructions tell the model how to rewrite follow-up questions,
# answer using document evidence, and compress older chat turns into a summary.
CONDENSE = ("Given the chat history and the user's latest message, rewrite the latest message as a standalone question "
            "by replacing only the pronouns or references "
            "('it', 'that', 'them', 'the lowest', 'and sick leave?') with what they refer to in the chat history. "
            "Do not add any other detail from the chat. Return ONLY the question.")
ANSWER = """You answer questions about the user's documents and remember the conversation.
- Facts about the documents: use ONLY the document context below. For totals, counts, highest and lowest, use the sheet summaries first.
  One row is one transaction; 'Units' is a different number from the number of transactions. 'Revenue Target' is not 'Revenue'.
- What the user said, asked, or asked you to remember: use the chat history and the conversation summary.
- If the answer is in neither, say you could not find it. Never invent anything.
- Answer directly in one or two sentences and do not mention these rules.

Conversation summary: {summary}

Document context:
{context}"""

SUMMARIZE = "Update this conversation summary with the new lines. Keep names, numbers and topics.\nSummary so far: {summary}\nNew lines:\n{lines}\nUpdated summary:"


# Data-source helpers.
# These functions normalize spreadsheet URLs and load the data into retrievable
# document chunks plus summary documents that capture small-sheet statistics.
def sheet_url(src):
    """A Google Sheets link becomes its CSV export link (the sheet must be shared 'anyone with the link can view')."""
    m = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", src)
    gid = re.search(r"gid=(\d+)", src)
    return f"https://docs.google.com/spreadsheets/d/{m[1]}/export?format=csv&gid={gid[1] if gid else 0}" if m else src


def load_sheet(src):
    """Google Sheet link, .csv or .xlsx -> one text Document per row + one summary Document per sheet.
    The summary holds whole-sheet numbers (counts, totals by category) that no single row contains."""
    label = "Google Sheet" if "docs.google.com" in src else os.path.basename(src)
    try:
        sheets = pd.read_excel(src, sheet_name=None) if src.lower().endswith((".xlsx", ".xls")) else {"Sheet1": pd.read_csv(sheet_url(src))}
    except Exception as e:
        raise ValueError(f"Could not read '{label}' ({e}). For Google Sheets, share it as 'Anyone with the link can view'.")
    rows, summaries = [], []
    for name, df in sheets.items():
        df = df.dropna(how="all")
        for c in df.select_dtypes("datetime"):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
        rows += [Document(f"{name} | " + "; ".join(f"{c}: {v}" for c, v in r.items() if pd.notna(v)),
                          metadata={"source": label, "sheet": name, "row": i + 2}) for i, r in df.iterrows()]

        summaries.append(Document(summarize_sheet(name, df), metadata={"source": label, "sheet": name}))
    return rows, summaries


def summarize_sheet(name, df):
    """Plain one-line facts (totals, rows per category, sum per category with highest/lowest) that a small model can quote."""
    n = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
    nums = [c for c in df.select_dtypes("number") if "price" not in str(c).lower()]
    lines = [f"Summary of sheet '{name}': {len(df)} rows (each row is one record/transaction). Columns: {', '.join(map(str, df.columns))}."]
    lines += [f"Total {c} in sheet '{name}': {n(df[c].sum())}." for c in nums]
    for g in df.select_dtypes(exclude=["number", "datetime"]):
        if 2 <= df[g].nunique() <= 12:
            lines.append(f"Number of transactions (rows) by {g} in sheet '{name}': " + ", ".join(f"{k} {v}" for k, v in df[g].value_counts().sort_index().items()) + ".")
            for c in nums:
                s = df.groupby(g)[c].sum()
                lines.append(f"{c} by {g} in sheet '{name}': " + ", ".join(f"{k} {n(v)}" for k, v in s.items()) + f". Highest: {s.idxmax()}. Lowest: {s.idxmin()}.")
    return "\n".join(lines)


# Citation helper.
# This keeps source traceability for each retrieved chunk so the app can tell the
# user which document page or sheet row supported the answer.
def cite(d):
    m = d.metadata
    return f"{m['source']} " + (f"p.{m['page'] + 1}" if "page" in m else f"{m.get('sheet')} " + (f"row {m['row']}" if "row" in m else "summary"))


# Core RAG assistant.
# The assistant combines retrieved document chunks, chat memory, and a running
# summary to answer both direct and follow-up questions while keeping the context
# grounded in source material.
class Assistant:
    def __init__(self, sources, llm=None, embeddings=None, k=4, max_turns=None):
        """max_turns=None keeps the full chat history (buffer memory). With max_turns=N the last N turns are kept
        word for word and older turns are folded into a running summary (buffer-summary memory)."""
        self.llm = llm or ChatOllama(model=os.getenv("OLLAMA_MODEL", "llama3.2"), temperature=0, num_ctx=8192)
        docs, self.summaries = [], []
        for s in sources:
            if s.lower().endswith(".pdf"):
                docs += RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100).split_documents(PyPDFLoader(s).load())
            else:
                rows, summ = load_sheet(s)
                docs, self.summaries = docs + rows, self.summaries + summ
        embeddings = embeddings or OllamaEmbeddings(model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
        self.retriever = FAISS.from_documents(docs, embeddings).as_retriever(search_kwargs={"k": k})
        self.max_turns = max_turns
        self.reset()
        chain = lambda system: ChatPromptTemplate.from_messages([("system", system), MessagesPlaceholder("history"), ("human", "{question}")]) | self.llm | StrOutputParser()
        self.condense, self.answer = chain(CONDENSE), chain(ANSWER)
        self.summarize = ChatPromptTemplate.from_template(SUMMARIZE) | self.llm | StrOutputParser()

    # Conversation-state reset.
    # A new conversation clears the message list, the LLM history, and the rolling summary.
    def reset(self):
        """Start a new conversation (forget history, summary and the list of user messages)."""
        self.history, self.summary, self.user_messages = [], "", []

    # Follow-up detection.
    # These helpers decide whether a user message depends on previous turns, such as
    # pronouns like "it" or "the lowest", or whether it is a standalone question.
    @staticmethod
    def _is_follow_up(message):
        return re.search(r"^(and|also|but|what about|how about)\b|\b(it|its|they|them|their|that|those|these|this|he|she|his|her|one|ones|same)\b",
                         message.strip().lower()) is not None

    @staticmethod
    def _looks_like_question(message):
        text = message.strip().lower()
        return (
            "?" in text
            or re.match(
                r"^(what|who|when|where|why|how|which|whose|"
                r"whom|can|could|would|will|should|do|does|did|"
                r"is|are|am|was|were|have|has|had)\b",
                text,
            ) is not None
        )

    def _is_memory_question(self, question):
        text = question.lower()
        patterns = [
            r"\bmy favorite\b",
            r"\bwhat code\b",
            r"\bwhat did i (?:say|ask|tell you|share)\b",
            r"\bwhat have i (?:said|asked|told you|shared)\b",
            r"\bwhat do you remember about me\b",
            r"\bremember(?:ed)? (?:this|that|my)\b",
        ]
        return any(re.search(p, text) for p in patterns)

    # Main answer flow.
    # This method handles first-message queries, memory-based questions, and regular
    # retrieval-grounded questions while preserving conversational context.
    def ask(self, question):
        previous_messages = self.user_messages.copy()
        text = question.strip().lower()

        # Answer first-message / first-question requests deterministically.
        if re.search(r"\b(first|earliest) message\b", text):
            reply = (
                f'Your first message was: "{previous_messages[0]}"'
                if previous_messages
                else "There is no earlier user message in this conversation."
            )
            docs = []

        elif re.search(r"\b(first|earliest) question\b", text):
            previous_questions = [
                m for m in previous_messages
                if self._looks_like_question(m)
            ]
            reply = (
                f'Your first question was: "{previous_questions[0]}"'
                if previous_questions
                else "I could not find an earlier question in this conversation."
            )
            docs = []

        else:
            is_memory = self._is_memory_question(question)

            if is_memory:
                # Personal-memory questions use conversation history,
                # not retrieved document passages.
                docs = []
                reply = self.answer.invoke({
                    "summary": self.summary or "none",
                    "context": "No document context is relevant to this question.",
                    "history": self.history,
                    "question": question,
                })
            else:
                # Rewrite only real follow-ups ("and the lowest?"); standalone questions are left untouched.
                standalone = (
                    self.condense.invoke({"history": self.history, "question": question})
                    if self.history and self._is_follow_up(question) else question
                )

                # Sheet summaries are always included (they are short), so totals/counts are never missed.
                docs = self.summaries + self.retriever.invoke(standalone)

                # The standalone query guides retrieval, while prior turns and
                # the running summary remain available for conversational memory.
                reply = self.answer.invoke({
                    "summary": self.summary or "none",
                    "context": "\n\n".join(
                        d.page_content for d in docs
                    ),
                    "history": self.history,
                    "question": standalone,
                })

        self.user_messages.append(question)
        self.history += [HumanMessage(question), AIMessage(reply)]

        if self.max_turns and len(self.history) > 2 * self.max_turns:
            old = self.history[:-2 * self.max_turns]
            self.history = self.history[-2 * self.max_turns:]

            self.summary = self.summarize.invoke({
                "summary": self.summary or "none",
                "lines": "\n".join(
                    f"{m.type}: {m.content}" for m in old
                ),
            })

        return reply, docs



# Command-line entry point.
# This lets the app run as a local chat tool: it loads the source documents,
# then accepts questions until the user types 'quit'.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", help="PDF files, Google Sheet links, or .csv / .xlsx files")
    ap.add_argument("--max-turns", type=int, help="summary memory: keep this many recent turns, summarise older ones")
    args = ap.parse_args()
    try:
        bot = Assistant(args.sources, max_turns=args.max_turns)
        print("Ready. Ask a question ('quit' to exit).")
        while (q := input("\nYou: ").strip()).lower() not in ("quit", "exit"):
            if q:
                reply, docs = bot.ask(q)
                print(f"\nAssistant: {reply}\n  Sources: " + "; ".join(dict.fromkeys(map(cite, docs))))
    except (EOFError, KeyboardInterrupt):
        pass
    except Exception as e:
        sys.exit(f"Error: {e}\nIs Ollama running, with the models installed? (ollama pull llama3.2 && ollama pull nomic-embed-text)")


if __name__ == "__main__":
    main()