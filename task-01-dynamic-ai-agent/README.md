# AI Agent for Dynamic Task Execution (free local LLM via Ollama)

A command-line agent where a real LLM running locally in Ollama is the decision engine. For each message the model
works out the intent, fills in the JSON arguments, chooses a tool, and writes the final answer from the tool's real
result. There are no keyword rules or scripted scenarios, and no API keys or internet are needed after the model download.



## Files

| File | Purpose |
|---|---|
| `agent.py` | Ollama client, agent loop, command-line chat |
| `tools.py` | The three tools and their JSON schemas |
| `test_agent.py` | 19 offline tests |

## Tools

| Tool | What it does |
|---|---|
| `schedule_manager` | Create / update / delete / list events from `event_name`, `date` (YYYY-MM-DD), `time` (HH:MM). Overlapping events return a `conflict` warning and nothing is saved until the user confirms. Events are kept in `schedule.json`. |
| `location_info` | Country, time zone and current local time for about 60 major cities/countries, plus any city that has its own IANA time zone. Unknown places return `not_found`. |
| `analytics` | Count, average, maximum, minimum. Invalid entries are skipped and reported; empty or all-invalid input gives a clear error. |

## Run

```bash
ollama pull llama3.2                 
python agent.py --verbose            
```

`--model qwen2.5:7b` (or `llama3.1:8b`) is slower but follows tool schemas and dates more reliably than the
default 3B model. The model must support tool calling. Environment variables: `OLLAMA_HOST`, `OLLAMA_MODEL`.

Example prompts:

```
Book a design review on 2026-10-12 at 14:00 for 45 minutes
Add a client call the same day at 14:30                   -> conflict warning
Move the design review to 16:00
What time is it in Tokyo and which country is that?
Stats for 12, 7, 19, 4, abc, 30
Delete the design review
```

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

The tests cover each tool's normal and error cases, the agent loop driven by a scripted stand-in for the model,
and the Ollama client against a stub server. They cannot judge how well a real model picks tools,
so try the prompts above.

## Notes

- Small models sometimes write a tool call as JSON text, or send numbers as strings. The agent accepts both.
- Relative dates ("tomorrow") work because the current date and time are given to the model on every turn.
