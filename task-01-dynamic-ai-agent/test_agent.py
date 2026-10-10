import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import agent as agent_mod
from agent import MAX_STEPS, Agent, Ollama, OllamaError, _coerce
from tools import Schedule, analytics, location_info


# =========================================================================== tools
@pytest.fixture
def cal(tmp_path):
    return Schedule(str(tmp_path / "s.json"))


def test_schedule_create_and_conflict(cal):
    assert cal.run("create", event_name="Standup", date="2026-10-12", time="09:00", duration_minutes=30)["status"] == "created"
    clash = cal.run("create", event_name="Dentist", date="2026-10-12", time="09:15")
    assert clash["status"] == "conflict" and clash["conflicts"][0]["name"] == "Standup" and len(cal.events) == 1
    assert cal.run("create", event_name="Lunch", date="2026-10-12", time="09:30")["status"] == "created"  # back-to-back is fine
    assert cal.run("create", event_name="Other day", date="2026-10-13", time="09:00")["status"] == "created"


def test_schedule_force_update_delete(cal):
    cal.run("create", event_name="A", date="2026-10-12", time="10:00")
    forced = cal.run("create", event_name="B", date="2026-10-12", time="10:30", force=True)
    assert forced["status"] == "created" and "warning" in forced
    moved = cal.run("update", event_name="B", new_time="14:00")
    assert moved["status"] == "updated" and moved["event"]["time"] == "14:00"
    assert cal.run("update", event_name="B", new_time="10:15")["status"] == "conflict"
    assert cal.run("delete", event_name="A")["status"] == "deleted"
    assert cal.run("delete", event_name="A")["status"] == "not_found"
    assert cal.run("list", date="2026-10-12")["count"] == 1


def test_schedule_ambiguous_and_invalid(cal):
    cal.run("create", event_name="Gym", date="2026-10-12", time="07:00")
    cal.run("create", event_name="Gym", date="2026-10-13", time="07:00")
    assert cal.run("delete", event_name="Gym")["status"] == "ambiguous" and len(cal.events) == 2
    assert cal.run("delete", event_name="Gym", date="2026-10-13")["status"] == "deleted"
    for bad in (dict(event_name="X", date="12/10/2026", time="9am"), dict(event_name="X"), dict(event_name="X", date="2026-02-30", time="10:00"),
                dict(event_name="X", date="2026-10-12", time="10:00", duration_minutes=-5)):
        assert cal.run("create", **bad)["status"] == "error"
    assert cal.run("explode")["status"] == "error"


def test_schedule_persists(tmp_path):
    p = str(tmp_path / "s.json")
    Schedule(p).run("create", event_name="Keep", date="2026-10-12", time="08:00")
    assert len(Schedule(p).events) == 1


def test_location():
    r = location_info("Cairo")
    assert (r["status"], r["country"], r["time_zone"]) == ("ok", "Egypt", "Africa/Cairo") and len(r["current_local_time"]) == 19
    assert location_info("Paris, France")["country"] == "France"
    assert location_info("Paris, Texas")["status"] == "not_found"  # the table only knows Paris, France
    assert location_info("Reykjavik")["time_zone"] == "Atlantic/Reykjavik"
    for bad in ("Zzzxqv Nowhere", "", "   ", None, 42, ", ,"):
        assert location_info(bad)["status"] in ("not_found", "error")


def test_analytics():
    r = analytics([1, 2, 3, "4", "x", True])
    assert (r["count"], r["average"], r["maximum"], r["minimum"]) == (4, 2.5, 4, 1) and r["ignored_invalid_values"] == ["x", True]
    assert analytics(["1,200", 800])["average"] == 1000
    for bad in ([], None, "12, 7", ["a", "b"], 5):
        assert analytics(bad)["status"] == "error"


def test_coerce_repairs_small_model_output():
    assert _coerce({"values": "12, 7 ;19"})["values"] == ["12", "7", "19"]
    assert _coerce({"values": "[1, 2, 3]"})["values"] == [1, 2, 3]
    assert _coerce({"values": "[1, two]"})["values"] == ["1", "two"]
    assert _coerce({"duration_minutes": "45", "force": "True", "date": None}) == {"duration_minutes": 45, "force": True}
    assert _coerce("junk") == {}


# =========================================================================== agent loop
def call(name, args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def say(text):
    return {"role": "assistant", "content": text}


class ScriptedLLM:
    """Stands in for the model: returns pre-written messages and records what it was sent."""

    def __init__(self, *script):
        self.script, self.seen = list(script), []

    def chat(self, messages, tools):
        self.seen.append((json.loads(json.dumps(messages)), tools))  
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(tmp_path, *script):
    return Agent(ScriptedLLM(*script), schedule_path=str(tmp_path / "s.json"))


def test_tool_result_is_fed_back_and_final_answer_returned(tmp_path):
    a = make(tmp_path, call("analytics", {"values": [1, 2, 3]}), say("The average is 2."))
    assert a.chat("average of 1 2 3") == "The average is 2."
    msgs, tools = a.llm.seen[1]
    assert msgs[0]["role"] == "system" and "Current date and time" in msgs[0]["content"]
    tool_msg = msgs[-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_name"] == "analytics" and '"average": 2.0' in tool_msg["content"]
    assert [t["function"]["name"] for t in tools] == ["schedule_manager", "location_info", "analytics"]
    assert all(m["role"] != "system" for m in a.history)  # the system prompt is rebuilt each turn, not stored


def test_conflict_flow_across_two_turns(tmp_path):
    a = make(tmp_path,
             call("schedule_manager", {"action": "create", "event_name": "Design review", "date": "2026-10-12", "time": "14:00", "duration_minutes": 45}),
             say("Booked."),
             call("schedule_manager", {"action": "create", "event_name": "Client call", "date": "2026-10-12", "time": "14:30"}),
             say("That overlaps with the design review. Another time?"))
    a.chat("Book a design review on 12 Oct at 2pm for 45 minutes")
    reply = a.chat("Add a client call at 2:30pm the same day")
    assert "overlaps" in reply and len(a.schedule.events) == 1
    assert json.loads(a.llm.seen[3][0][-1]["content"])["status"] == "conflict"
    assert len(a.llm.seen[2][0]) > len(a.llm.seen[0][0])  # earlier turns stay in the conversation


def test_tool_call_written_as_json_text_is_accepted(tmp_path):
    a = make(tmp_path, say('```json\n{"name": "location_info", "parameters": {"location": "Tokyo"}}\n```'), say("It is evening in Tokyo."))
    assert a.chat("time in Tokyo?") == "It is evening in Tokyo."
    assert json.loads(a.llm.seen[1][0][-1]["content"])["time_zone"] == "Asia/Tokyo"
    b = make(tmp_path, say('{"name": "unknown_tool", "parameters": {}}'))
    assert b.chat("hi") == '{"name": "unknown_tool", "parameters": {}}'


def test_string_arguments_are_repaired(tmp_path):
    a = make(tmp_path, call("analytics", {"values": "12, 7, 19, 4, abc, 30"}), say("done"),
             call("schedule_manager", {"action": "create", "event_name": "X", "date": "2026-10-12", "time": "10:00", "duration_minutes": "90", "force": "false"}), say("ok"))
    a.chat("stats")
    r = json.loads(a.llm.seen[1][0][-1]["content"])
    assert r["status"] == "ok" and r["count"] == 5 and r["ignored_invalid_values"] == ["abc"]
    a.chat("book")
    assert list(a.schedule.events.values())[0]["duration_minutes"] == 90


def test_arguments_sent_as_json_string(tmp_path):
    a = make(tmp_path, call("location_info", json.dumps({"location": "Cairo"})), say("ok"))
    a.chat("where is cairo")
    assert json.loads(a.llm.seen[1][0][-1]["content"])["country"] == "Egypt"


def test_wrong_tool_or_arguments_become_error_results_the_model_can_see(tmp_path):
    a = make(tmp_path, call("teleport", {}), call("analytics", {"numbers": [1]}), call("analytics", {"values": [1]}), say("recovered"))
    assert a.chat("go") == "recovered"
    results = [json.loads(m["content"]) for m in a.history if m["role"] == "tool"]
    assert [r["status"] for r in results] == ["error", "error", "ok"] and "Unknown tool" in results[0]["message"]


def test_model_failure_leaves_history_clean(tmp_path):
    a = make(tmp_path, call("analytics", {"values": [1]}), OllamaError("Cannot reach Ollama"), say("fine now"))
    with pytest.raises(OllamaError):
        a.chat("first")
    assert a.history == []  
    assert a.chat("second") == "fine now"


def test_runaway_tool_loop_is_stopped(tmp_path):
    a = make(tmp_path, *[call("analytics", {"values": [1]})] * (MAX_STEPS + 2))
    assert "step limit" in a.chat("loop")
    assert len(a.llm.seen) == MAX_STEPS


def test_empty_model_reply(tmp_path):
    assert "didn't get a response" in make(tmp_path, say("")).chat("hello")


# =========================================================================== Ollama client 
class Stub(BaseHTTPRequestHandler):
    seen = []
    mode = "ok"

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"models": [{"name": "llama3.2:latest"}]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.seen.append(payload)
        if Stub.mode == "missing":
            return self._send(404, {"error": "model 'llama3.2' not found"})
        if Stub.mode == "no_tools":
            return self._send(400, {"error": "registry.ollama.ai/library/gemma:2b does not support tools"})
        if Stub.mode == "garbage":
            return self._send(200, {"unexpected": True})
        self._send(200, {"message": call("analytics", {"values": [1]})})

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    Stub.seen, Stub.mode = [], "ok"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_client_sends_tools_and_returns_the_message(server):
    msg = Ollama(host=server).chat([{"role": "user", "content": "hi"}], agent_mod.TOOL_SCHEMAS)
    sent = Stub.seen[0]
    assert sent["stream"] is False and sent["options"]["temperature"] == 0 and sent["model"] == "llama3.2"
    assert len(sent["tools"]) == 3 and msg["tool_calls"][0]["function"]["name"] == "analytics"


def test_client_errors_are_explained(server):
    for mode, text in (("missing", "ollama pull llama3.2"), ("no_tools", "cannot use tools"), ("garbage", "no message")):
        Stub.mode = mode
        with pytest.raises(OllamaError, match=text):
            Ollama(host=server).chat([], [])
    with pytest.raises(OllamaError, match="Cannot reach Ollama"):
        Ollama(host="http://127.0.0.1:1", timeout=2).chat([], [])


def test_client_model_check_and_host_forms(server, monkeypatch):
    assert Ollama(host=server).has_model() and Ollama(host=server, model="llama3.2:latest").has_model()
    assert not Ollama(host=server, model="mistral").has_model()
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5")
    c = Ollama()
    assert c.host == "http://127.0.0.1:11434" and c.model == "qwen2.5"
