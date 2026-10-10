# Simple RAG System — PDF & Excel Q&A with Local LLMs

A lightweight Retrieval-Augmented Generation (RAG) system that allows users to ask natural-language questions about PDF, Excel, and CSV files. It retrieves the most relevant information and uses a locally running Large Language Model (LLM) through Ollama to generate grounded answers with source citations.

## Features

- **Multi-format Support:** Load and query PDF, Excel (`.xlsx`), CSV, and text files.
- **Local LLM Integration:** Generate answers using Ollama without relying on cloud-based LLM APIs.
- **Hybrid Retrieval:** Combine BM25 keyword search and semantic embedding similarity using Reciprocal Rank Fusion (RRF).
- **Document Chunking:** Split text into manageable passages with overlap to improve retrieval.
- **Spreadsheet Summaries:** Generate sheet-level overviews and category-based totals to support aggregation questions.
- **Source Citations:** Reference retrieved passages in generated answers.
- **Graceful Fallbacks:** Continue retrieving and displaying relevant passages when Ollama or a required model is unavailable.
- **Automated Testing:** Validate document loading, chunking, retrieval, error handling, and prompt-injection defenses.

## Tech Stack

- **Language:** Python
- **LLM Runtime:** Ollama
- **Generation Models:** Llama 3.2, Qwen 2.5
- **Embedding Model:** `nomic-embed-text`
- **Retrieval:** BM25, Embedding Similarity, Hybrid Search
- **Document Processing:** `pypdf`, `openpyxl`, Python `csv`
- **Testing:** `pytest`

## How It Works

1. **Load:** Extract text from PDF pages and read Excel sheets, CSV files, and supported text files.
2. **Chunk:** Split document text into overlapping passages. Convert spreadsheet rows into self-contained text chunks.
3. **Summarize Sheets:** Generate sheet-level overviews and selected category totals to help answer aggregation questions.
4. **Retrieve:** Find relevant passages using BM25 keyword search, semantic embeddings, or hybrid retrieval.
5. **Generate:** Pass the retrieved passages to the local LLM, which generates an answer grounded in the provided context.
6. **Cite:** Include references to the retrieved passages and indicate when the available context does not contain the answer.

## Installation

### 1. Install Ollama

Download and install Ollama from [ollama.com](https://ollama.com).

### 2. Download the Models

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

## Usage

Ask questions interactively about a PDF:

```bash
python rag_system.py data/handbook.pdf
```

Ask a specific question about an Excel file:

```bash
python rag_system.py data/sales.xlsx -q "Which region sold the most?"
```

Display the retrieved context:

```bash
python rag_system.py data/handbook.pdf --show-context
```

Use a different generation model:

```bash
python rag_system.py data/handbook.pdf --model qwen2.5:3b
```

Select a retrieval strategy:

```bash
python rag_system.py data/handbook.pdf --retriever hybrid
```

Other supported retrieval options include `bm25` and `embeddings`.

## Example Questions

| File | Question |
|---|---|
| `handbook.pdf` | How many days of annual leave do I get? |
| `handbook.pdf` | Can I work from another country? |
| `sales.xlsx` | Which region sold the most? |
| `sales.xlsx` | What is the West region's Q3 target? |

The sample files are fictional and can be generated using `make_sample_data.py`. You can also use your own supported documents.

## Configuration

The system supports command-line options and environment variables for customization.

| Option | Purpose |
|---|---|
| `--model` | Select the Ollama generation model |
| `--retriever` | Choose `bm25`, `embeddings`, or `hybrid` |
| `--top-k` | Set the number of passages to retrieve |
| `--rows-per-chunk` | Configure the number of spreadsheet rows per chunk |
| `--show-context` | Display retrieved passages |
| `--no-llm` | Disable LLM generation |
| `OLLAMA_HOST` | Configure the Ollama server address |
| `OLLAMA_MODEL` | Set the default generation model |
| `OLLAMA_EMBED_MODEL` | Set the embedding model |

## Testing

Run the automated test suite:

```bash
pytest -q
```

The tests cover document loading, chunking, retrieval quality, Ollama client behavior, missing-model fallbacks, and prompt-injection containment. The test suite does not require a running Ollama instance.

## Limitations

- Small local models may occasionally produce inaccurate answers or incorrect passage citations.
- Spreadsheet aggregation is limited to selected category columns and supported summary calculations.
- Excel formulas are read using their last saved values.
- Scanned PDFs require OCR before their text can be retrieved.
- Legacy `.xls` files must be converted to `.xlsx` or `.csv`.
- Embeddings are computed at startup and are not cached, which may increase indexing time for large files.

## Future Improvements

- Add persistent embedding storage and document indexing.
- Support more advanced spreadsheet calculations.
- Improve citation validation and answer-grounding evaluation.
- Add OCR support for scanned documents.
- Develop a web-based interface for uploading files and asking questions.

## License

Add a license file if you intend to distribute this project publicly.

---

**Project Goal:** Demonstrate a practical RAG pipeline that combines document processing, hybrid information retrieval, local LLM inference, and source-grounded question answering.