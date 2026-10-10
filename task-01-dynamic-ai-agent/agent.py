
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime

from tools import TOOL_SCHEMAS, Schedule, analytics, location_info

DEFAULT_MODEL = "llama3.2"
DEFAULT_HOST = "http://localhost:11434"
MAX_STEPS = 6

SYSTEM_PROMPT = """You are an assistant that completes the user's requests by calling tools.
Current date and time: {now}. Use it to turn 'today', 'tomorrow', 'next Friday' into exact YYYY-MM-DD dates.

Tools: schedule_manager (calendar events), location_info (country, time zone, local time of a place),
analytics (count / average / max / min of numbers).

How to work:
1. Decide what the user wants. If a tool fits, call it with exact values taken from the message.
2. If something required is missing (for example an event has no date or time), ask the user one short question instead of guessing.
3. Never invent tool results. After a tool returns, answer the user clearly from its result only.
4. If the result is a conflict, error or not_found, explain it plainly and suggest the next step.
   Only use force=true when the user explicitly asks to book despite a conflict.
5. If no tool is needed (greetings, general questions), just answer briefly."""


class OllamaError(Exception):
    pass


class Ollama:
    """Minimal client for Ollama's /api/chat endpoint (standard library only)."""

    def __init__(self, model: str | None = None, host: str | None = None, timeout: float = 300):
        host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.host = host if host.startswith("http") else f"http://{host}"
        self.model = model or os.environ.get("OLLAMA_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  

    def _call(self, path: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(self.host + path, data=json.dumps(payload).encode() if payload else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # before URLError: it is a subclass
            try:
                detail = str(json.loads(exc.read().decode("utf-8")).get("error", ""))
            except Exception:
                detail = ""
            low = detail.lower()
            if exc.code == 404 and "not found" in low:
                raise OllamaError(f"Model '{self.model}' is not installed. Run: ollama pull {self.model}") from None
            if "does not support tools" in low:
                raise OllamaError(f"Model '{self.model}' cannot use tools. Try llama3.2, llama3.1 or qwen2.5.") from None
            raise OllamaError(f"Ollama error (HTTP {exc.code}): {detail or exc.reason}") from None
        except (TimeoutError, socket.timeout):
            raise OllamaError(f"Ollama took longer than {self.timeout:.0f}s (the first request loads the model).") from None
        except (urllib.error.URLError, OSError):
            raise OllamaError(f"Cannot reach Ollama at {self.host}. Install it from https://ollama.com and start it.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise OllamaError("Ollama sent an unreadable response.") from None

    def has_model(self) -> bool:
        names = {m.get("name", "") for m in self._call("/api/tags").get("models", [])}
        return self.model in names or (":" not in self.model and f"{self.model}:latest" in names)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        data = self._call("/api/chat", {"model": self.model, "messages": messages, "tools": tools, "stream": False,
                                        "options": {"temperature": 0}})
        msg = data.get("message")
        if not isinstance(msg, dict):
            raise OllamaError("Ollama returned no message.")
        return msg


# --------------------------------------------------------------------------- 
def _coerce(args) -> dict:
    """Small models sometimes send numbers or lists as strings; repair the common cases."""
    if not isinstance(args, dict):
        return {}
    out = {}
    for key, val in args.items():
        if val is None:
            continue
        if isinstance(val, str):
            s = val.strip()
            if key == "values":
                try:
                    val = json.loads(s) if s.startswith("[") else [x for x in re.split(r"[,\s;]+", s) if x]
                except json.JSONDecodeError:
                    val = [x for x in re.split(r"[\[\],\s;]+", s) if x]
            elif key == "duration_minutes" and s.isdigit():
                val = int(s)
            elif key == "force":
                val = s.lower() in ("true", "yes", "1")
        out[key] = val
    return out


def _tool_call_in_text(content: str, names: set[str]) -> list[dict]:
    """Some models write the call as JSON text instead of a real tool call; accept that too."""
    s = re.sub(r"^```(?:json)?|```$", "", (content or "").strip(), flags=re.MULTILINE).strip()
    if not s.startswith("{"):
        return []
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return []
    args = obj.get("arguments", obj.get("parameters")) if isinstance(obj, dict) else None
    if isinstance(obj, dict) and obj.get("name") in names and isinstance(args, dict):
        return [{"function": {"name": obj["name"], "arguments": args}}]
    return []


class Agent:
    def __init__(self, llm=None, schedule_path: str = "schedule.json", verbose: bool = False):
        self.llm = llm or Ollama()
        self.schedule = Schedule(schedule_path)
        self.verbose = verbose
        self.history: list[dict] = []
        self._tools = {
            "schedule_manager": self.schedule.run,
            "location_info": location_info,
            "analytics": analytics,
        }

    def _log(self, text: str) -> None:
        if self.verbose:
            print(text, file=sys.stderr)

    def _run_tool(self, name: str, args) -> dict:
        fn = self._tools.get(name)
        if fn is None:
            return {"status": "error", "message": f"Unknown tool '{name}'. Available: {', '.join(self._tools)}."}
        try:
            return fn(**_coerce(args))
        except TypeError as exc:  
            return {"status": "error", "message": f"Bad arguments for {name}: {exc}"}
        except Exception as exc:  
            return {"status": "error", "message": f"{name} failed: {exc}"}

    def chat(self, user_input: str) -> str:
        start = len(self.history)
        self.history.append({"role": "user", "content": user_input})
        system = {"role": "system", "content": SYSTEM_PROMPT.format(now=datetime.now().strftime("%A %Y-%m-%d %H:%M"))}
        try:
            for _ in range(MAX_STEPS):
                msg = self.llm.chat([system] + self.history, TOOL_SCHEMAS)
                calls = msg.get("tool_calls") or _tool_call_in_text(msg.get("content", ""), set(self._tools))
                if not calls:
                    self.history.append({"role": "assistant", "content": msg.get("content", "")})
                    return (msg.get("content") or "").strip() or "Sorry, I didn't get a response from the model."
                self.history.append({"role": "assistant", "content": "" if not msg.get("tool_calls") else msg.get("content", ""), "tool_calls": calls})
                for call in calls:
                    fn = call.get("function", {})
                    name, args = fn.get("name", ""), fn.get("arguments", {})
                    if isinstance(args, str):  
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    self._log(f"[tool selected] {name}\n[extracted JSON] {json.dumps(args, ensure_ascii=False)}")
                    result = self._run_tool(name, args)
                    self._log(f"[tool result] {json.dumps(result, ensure_ascii=False)}")
                    self.history.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
        except Exception:
            self.history = self.history[:start]  
            raise
        return "Sorry, I couldn't finish that within the step limit. Please rephrase or break it into smaller requests."


def main() -> None:
    ap = argparse.ArgumentParser(description="Tool-using agent powered by a free Ollama model")
    ap.add_argument("--model", help=f"Ollama model (default {DEFAULT_MODEL}, or $OLLAMA_MODEL)")
    ap.add_argument("--verbose", action="store_true", help="show the chosen tool, the JSON arguments and the result")
    ap.add_argument("--schedule-file", default="schedule.json")
    args = ap.parse_args()

    llm = Ollama(model=args.model)
    try:
        if not llm.has_model():
            sys.exit(f"Model '{llm.model}' is not installed. Run: ollama pull {llm.model}")
    except OllamaError as exc:
        sys.exit(str(exc))

    agent = Agent(llm, schedule_path=args.schedule_file, verbose=args.verbose)
    print(f"Agent ready (model: {llm.model}). Type a request, or 'quit'.")
    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("quit", "exit"):
            break
        if text:
            try:
                print(f"\nAgent: {agent.chat(text)}")
            except OllamaError as exc:
                print(f"\nAgent: {exc}")


if __name__ == "__main__":
    main()
