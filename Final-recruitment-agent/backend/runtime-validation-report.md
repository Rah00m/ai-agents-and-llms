# Runtime Validation Report

**Generated**: 2026-10-20T19:36:00+03:00  
**Target**: `backend/` recruitment pipeline (Foundation, retrievers, agents, and orchestrator)

## Summary

| Step | Status | Exit Code | Details |
|------|--------|-----------|---------|
| Startup | N/A | n/a | This scope is a Python pipeline/library; no FastAPI application entrypoint or readiness endpoint is present. |
| Unit and integration tests | PASS | 0 | `py -m pytest -q`: 70 passed in 1.23s across 4 test files. |
| Mock workflow | PASS | 0 | `py run_day2.py J1 --mode mock`: 8 candidates ranked, all stages completed, 0.039s total. |
| Ollama workflow | PASS | 0 | `py run_day2.py J1 --mode ollama`: 8 candidates processed, all stages completed, 123.238s total. |
| Browser E2E | N/A | n/a | No rendered web surface is part of the tested Day-1/Day-2 backend scope. |

**Overall**: PASS

## Coverage

- **Retrievers and data**: all 8 PDFs, 3 jobs, and 8 GitHub mock profiles are loaded; candidate IDs are checked for uniqueness and ground-truth coverage.
- **Error handling**: missing directories/files, malformed CSV, corrupt PDFs, blank PDFs, unknown GitHub users, duplicate candidates, and live GitHub failures are covered.
- **Skill extractor**: structured profiles, evidence quoted from CV text, incomplete CVs, empty CVs, mock mode, and LLM feedback plumbing are covered.
- **Matcher**: weighted scoring, preferred-skill redistribution, basic skill weighting, exact canonical skill matching, missing skills, unknown experience, deterministic explanations, and GitHub evidence behavior are covered.
- **QA agent**: unsupported skills, fabricated/missing evidence, contradictory or implausible years, missing data, thin CVs, and stale matches are covered.
- **Orchestrator**: retrieval through ranking, persistence/reload, stage events, unknown jobs/modes, retry with feedback, permanent QA rejection, per-candidate failure isolation, and LLM availability checks are covered.

## Environment Evidence

```text
Docker: unavailable — docker: command not found
Node.js: available — v22.20.0
Ollama: reachable; qwen2.5:7b installed
```

The Docker axis is not applicable to this backend pipeline because it has no database, broker, or container-managed external dependency. The browser axis is not applicable because this validation scope has no HTTP or rendered UI surface.

## Test Evidence

- [tests/test_retrievers.py](./tests/test_retrievers.py)
- [tests/test_agents.py](./tests/test_agents.py)
- [tests/test_workflow.py](./tests/test_workflow.py)
- [tests/test_llm.py](./tests/test_llm.py)

The real Ollama run completed successfully, but it took approximately 123 seconds for eight candidates on the local model. Mock mode remains the appropriate fast regression path.

## Issues Found

No blocking defects were found. The LLM run produced `approved_with_warnings` for candidates where the model output required QA warnings, but the workflow completed and ranked all eight candidates without crashing.

## Verdict

```yaml
environment:
  docker: UNAVAILABLE — docker: command not found
  node: AVAILABLE — v22.20.0
  playwright: SKIPPED — no browser/UI surface in Day-1/Day-2 backend scope
  infra-tier: NOT_APPLICABLE — no external infrastructure dependency
  browser-tier: NOT_APPLICABLE — no HTTP or rendered UI entrypoint
startup: NOT_APPLICABLE — Python pipeline/library, no application readiness endpoint
integration: PASS — exit_code: 0, passed: 70, failed: 0, skipped: 0, pytest suite plus mock workflow
e2e: NOT_APPLICABLE — exit_code: 0, backend workflow exercised directly in mock and Ollama modes
overall: PASS — retrievers, agents, error isolation, orchestration, persistence, and both LLM modes verified
```
