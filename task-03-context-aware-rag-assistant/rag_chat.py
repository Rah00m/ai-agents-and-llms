
# Setup:
#   ollama pull llama3.2
#   ollama pull nomic-embed-text
#   pip install langchain-core langchain-community langchain-text-splitters langchain-ollama pypdf pandas openpyxl
#
# Run:
#   python rag_chat.py file.pdf
#   python rag_chat.py file.xlsx

import sys
import pandas as pd
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import ChatOllama, OllamaEmbeddings

# 1. Load PDF or Excel
if len(sys.argv) < 2:
    sys.exit("Usage: python rag_chat.py file.pdf (or file.xlsx)")

path = sys.argv[1]

if path.lower().endswith(".pdf"):
    docs = PyPDFLoader(path).load()
elif path.lower().endswith((".xlsx", ".xls")):
    rows = pd.read_excel(path).fillna("").to_dict("records")
    docs = [
        Document(page_content=", ".join(f"{k}: {v}" for k, v in row.items()))
        for row in rows
    ]
else:
    sys.exit("Unsupported file type. Use PDF or Excel.")

# 2. Split document into chunks
chunks = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200
).split_documents(docs)

if not chunks or not any(d.page_content.strip() for d in chunks):
    sys.exit("No readable text found in the file.")

# 3. Create retriever
store = InMemoryVectorStore.from_documents(
    chunks,
    OllamaEmbeddings(model="nomic-embed-text")
)
retriever = store.as_retriever(search_kwargs={"k": 5})

# 4. Create LLM and prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful document-based assistant.
Answer using only the retrieved document context.
Explain technical terms clearly and organize answers when useful.
Use conversation history to understand follow-up questions,
but do not treat it as a source of facts.
If the retrieved context does not contain the answer,
say that the document does not provide enough information.

Document context:
{context}"""),
    MessagesPlaceholder("history"),
    ("human", "{question}")
])

chain = prompt | ChatOllama(model="llama3.2", temperature=0)

# 5. Conversation memory
history = []

# 6. Chat loop
while True:
    q = input("\nYou: ").strip()

    if q.lower() in ("exit", "quit"):
        break
    if not q:
        continue

    # Include the last 3 user questions to improve follow-up retrieval
    previous_questions = [
        m.content for m in history if isinstance(m, HumanMessage)
    ][-3:]
    search = " ".join(previous_questions + [q])

    # Retrieve relevant document chunks
    context = "\n\n".join(
        d.page_content for d in retriever.invoke(search)
    )

    # Generate context-aware answer
    answer = chain.invoke({
        "context": context,
        "history": history,
        "question": q
    }).content

    print(f"AI: {answer}")

    # Save conversation
    history.extend([HumanMessage(content=q), AIMessage(content=answer)])
