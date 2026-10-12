# Task 3: Context-Aware RAG Chat Assistant with Memory

## Project Description
This project implements an AI chat assistant using Retrieval-Augmented Generation (RAG), LangChain, and Ollama. The assistant answers questions based on a provided PDF or Excel file and uses conversation history to understand follow-up questions and maintain context throughout the conversation.

## Features
- Load and process PDF or Excel documents.
- Split document content into smaller chunks.
- Retrieve relevant information using embeddings and a vector store.
- Generate answers using the local Llama 3.2 language model.
- Store previous user messages and AI responses in conversation memory.
- Combine retrieved document content, conversation history, and the current question to generate context-aware answers.

## Requirements
- Python
- [Ollama](https://ollama.com/download)

Install the required libraries:

```bash
pip install langchain-core langchain-community langchain-text-splitters langchain-ollama pypdf pandas openpyxl
```

Download the required models:

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

## How to Run

For a PDF file:

```bash
python rag_chat.py file.pdf
```

For an Excel file:

```bash
python rag_chat.py file.xlsx
```

Ask questions interactively. Type `exit` or `quit` to end the conversation.

## Workflow
1. Load the PDF or Excel document.
2. Split the content into chunks.
3. Generate embeddings and create a retriever.
4. Retrieve relevant document information for each question.
5. Combine the retrieved context with conversation history.
6. Generate and display an answer using Llama 3.2.
7. Save each question and answer in memory for follow-up questions.

## Notes
- Ollama runs the language model locally without requiring a paid LLM API.
- Scanned PDFs require OCR before their text can be retrieved.
- Conversation memory is maintained during the current session only.