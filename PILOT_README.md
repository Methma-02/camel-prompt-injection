# I0 feasibility spike (counterfactual label oracle)

Added files only. CaMeL's own code, and the local-model changes
(`src/camel/local_openai_client.py`, `src/camel/models.py`), are unchanged.

| File | Requirement | What it does |
|---|---|---|
| `pilot/label_logger.py` | FR2 | Wraps a CaMeL policy engine; logs every tool call, each argument's label and the control context. `observe=True` logs the decision but lets the call run. |
| `pilot/plans.py` | FR3 | Four fixed Banking plans and their edits to untrusted files (changed fact, removed document, branch flip, benign default). |
| `pilot/qllm.py` | - | Quarantined LLM: `stub` (deterministic), or a model name passed to CaMeL's own `query_quarantined_llm` (e.g. `openai:llama31-camel`). |
| `pilot/oracle.py` | FR3-FR5 | Repeated unedited and edited runs, call matching, a changed / unchanged / unstable verdict per edit, TP/FP/FN/TN per slot. |
| `pilot/run_pilot.py` | FR5 | Command line; writes `results.md`, `slots.json`, `cells.json`, `runs.json`. |
| `tests/test_pilot/test_pilot.py` | NFR | Tests, including the differential test (observe mode leaves the environment as a no-policy run would). |

## Run (PowerShell, in D:\fyp\camel-prompt-injection)

```
uv run pytest tests/test_pilot -q
uv run python -m pilot.run_pilot --qllm stub --out pilot_out_stub
uv run --env-file .env python -m pilot.run_pilot --qllm openai:llama31-camel --repeats 5 --out pilot_out_llama_v2
```

The last command uses the same `.env` (`OPENAI_BASE_URL` = Ollama) and the same
`llama31-camel` model (temperature 0, 16k context) as the main.py runs, so Ollama must be running.
