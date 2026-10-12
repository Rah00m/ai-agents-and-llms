# AI Knowledge Assistant with Memory

Ask questions about PDFs and Google Sheets in a chat that remembers earlier turns. Built with LangChain, FAISS
and free local Ollama models (chat model `llama3.2`, embeddings `nomic-embed-text`).

| Project step | Where |
|---|---|
| 1. Data integration | `load_sheet` (Google Sheet link, `.csv`, `.xlsx` → one text line per row + a summary of totals), `PyPDFLoader` + text splitter for PDFs |
| 2. Embedding & indexing | `OllamaEmbeddings` → `FAISS` vector store (semantic search) |
| 3. RAG pipeline | `Assistant.ask`: retrieve the top 4 passages, the LLM answers only from them |
| 4. Memory | `Assistant.history` = full chat buffer; `--max-turns N` adds buffer-summary memory |
| 5. Testing & evaluation | `evaluate.py` (real model) and `test_assistant.py` (offline) |

## Setup and run

```bash
ollama pull llama3.2 && ollama pull nomic-embed-text
pip install -r requirements.txt
python assistant.py data/handbook.pdf data/sales.xlsx            # full-history memory
python assistant.py data/handbook.pdf "https://docs.google.com/spreadsheets/d/<ID>/edit" --max-turns 5
```

For a **Google Sheet**, use *Share → Anyone with the link → Viewer*, then paste the link (the tab in the link's
`gid=` is loaded). No Google account or API key is needed. `data/` has two fictional demo files (a company
handbook PDF and a sales workbook) used as stand-ins; use your own the same way.

Example chat:

```
You: Which region had the highest revenue?        -> North (91,840)
You: And the lowest?                              -> East   (follow-up: needs memory)
You: What is its Q3 revenue target?               -> 28,000 ("its" = East)
You: What was the first question I asked you?
```

## How the memory works

- **Buffer memory (default):** every question and answer is kept in `history` and sent to the model each turn,
  so it can answer "what did I ask before?".
- **Follow-up questions:** before searching, the model rewrites the latest message into a standalone question using
  the history ("And the lowest?" → "Which region had the lowest revenue?"). Searching with the raw follow-up would
  find nothing relevant.
- **Buffer-summary memory (optional, `--max-turns N`):** the last N turns stay word for word; older turns are folded
  into a running summary by the model, so long chats do not overflow the model's context.

## Evaluation

```bash
python evaluate.py     # needs Ollama running
```

It asks 10 single questions (including one whose answer is not in the documents, where the assistant must say so)
and 3 short conversations with follow-ups, then prints:

- **Answer accuracy:** the answer contains the correct fact (e.g. 21 days, North, 221,840)
- **Retrieval relevance:** the retrieved passages contained the answer
- **Follow-up / memory score:** follow-up questions answered correctly

The expected answers were checked against the data, and the sales figures against an independent pandas calculation.
I could not run `evaluate.py` with a real model while building this, so run it and report your scores.
`pytest -q` (12 tests) runs without Ollama, using fake models, and checks loading, indexing, retrieval, follow-up
rewriting and both memory modes.

## Design notes and limits

- Row passages cannot answer "which region sold the most?", so each sheet also gets a summary (row count, totals,
  totals by category) that is added to every question's context.
- The index is rebuilt at each start (fine for small files); `FAISS.save_local` can persist it.
- To use HuggingFace embeddings instead, pass `embeddings=HuggingFaceEmbeddings(...)` to `Assistant`.
- Small local models can miss details; try `OLLAMA_MODEL=qwen2.5:7b` or `llama3.1:8b` for better answers.
- `langchain-community` prints a sunset notice; its FAISS store still works. Chat history is a plain list of
  messages because LangChain's older memory classes are deprecated.
