"""Check that Ollama is ready.  Usage (from backend/): python check_llm.py"""
import asyncio

from pydantic import BaseModel

from app.config import settings
from app.llm import LLMError, check_ollama, chat_json


class Pong(BaseModel):
    reply: str


async def main() -> None:
    print(f"Ollama host : {settings.ollama_host}")
    print(f"Model       : {settings.ollama_model}")
    status = await check_ollama()
    if not status["reachable"]:
        print("\nOllama is NOT running.\n  1) Install it: https://ollama.com\n  2) Start it:   ollama serve")
        return
    if not status["model_installed"]:
        print(f"\nModel not installed. Run:  ollama pull {settings.ollama_model}")
        print("Installed models:", ", ".join(status["models"]) or "none")
        return
    print("\nOllama is running and the model is installed. Sending a test request...")
    try:
        out = await chat_json("You are a test bot.", 'Reply with JSON: {"reply": "pong"}', Pong)
        print("Model answered:", out.reply)
    except LLMError as exc:
        print("Test request failed:", exc)


if __name__ == "__main__":
    asyncio.run(main())
