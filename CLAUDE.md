# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Enterprise multi-agent system: a FastAPI/LangGraph backend orchestrating 5 specialized agents (RAG, Data Analyst, Search, Database, Integration) behind a Next.js 14 frontend. Core loop is a **PEV (Plan → Execute → Verify)** state machine built on LangGraph, with a strict schema-audit verifier to drive hallucination toward zero. Docs/comments in the codebase are largely Vietnamese; code identifiers are English.

## Commands

### Backend (Python 3.11/3.12)
```bash
python -m venv venv && venv\Scripts\activate     # Windows
pip install -r requirements.txt

# Run backend locally (requires postgres/redis up — see docker-compose)
uvicorn src.gateway.main:app --host 0.0.0.0 --port 8000 --reload

# Ingest sample documents into pgvector (rag_chunks table)
python run_ingestion.py

# Tests — no pytest.ini; each file is independent, run individually or all together
python -m pytest tests/ -v
python -m pytest tests/test_hardened_upgrades.py -v
python -m pytest tests/test_enterprise_upgrades.py -v
python -m pytest tests/test_architectural_upgrades.py -v
python -m pytest tests/test_audit_and_optimizations.py -v
python -m pytest tests/test_llm_routing_and_planner.py -v
python -m pytest tests/test_zero_trust_security.py -v

# Single test
python -m pytest tests/test_enterprise_upgrades.py::TestClassName::test_name -v

# Offline LLM-as-a-Judge evaluation against golden dataset -> eval_report.json/.md
python scripts/run_offline_eval.py
```

### Frontend (`frontend/`, Next.js 14 App Router)
```bash
cd frontend
npm install
npm run dev      # port 3000
npm run build
npm run lint
npm run test:e2e # Playwright, config at tests/e2e/playwright.config.ts
```

### Full stack via Docker Compose
```bash
docker-compose up -d --build   # 7 services: postgres, redis, backend, frontend, langfuse-web/worker, tei-reranker, python-sandbox
```
Ports: frontend `3001`, backend `8000` (Swagger at `/docs`), Langfuse `3005`, TEI reranker `8080`, Postgres `5432`, Redis `6379`.

`.env` (copy from `.env.example`) must set `OPENROUTER_API_KEY` at minimum; `TAVILY_API_KEY` enables `search_agent` web search.

## Architecture

### PEV Loop (the core control flow — read this before touching orchestration)
`src/orchestrator/core.py` builds a LangGraph `StateGraph` with three nodes: `planner → executor → verifier`, with a conditional edge back to `executor` on verification failure (max 2 retries, then the response is returned with a warning banner). State shape is `src/orchestrator/state.py` (`AgentState` TypedDict). Checkpointing is in-memory (`MemorySaver`, keyed by `session_id` as `thread_id`) — state is not persisted across process restarts.

- **Planner node**: picks `target_agent` and builds `plan`. Routing precedence: forced `agent_mode` → CSV attached (routes to `data_agent`, with dashboard-vs-text-only decided by keyword heuristics in the query) → compound-query decomposition into parallel DAG sub-tasks (`_decompose_subtasks`, fan-out/fan-in via `asyncio.gather` + LLM synthesis) → LLM planner call (`FAST_LLM_MODEL`) → keyword-based fallback route (`_determine_fallback_route`) if the LLM call fails.
- **Executor node**: resolves the agent via `AgentRegistry.lookup`, injects verifier feedback into the query on retry, and gates two sensitive operations behind **Human-in-the-Loop (HITL) approval** (see below) before calling `agent.process_csv_request` or `agent.process_request`.
- **Verifier node**: for CSV/dashboard results, runs a **strict schema audit** (`src/orchestrator/verifier.py::verify_dashboard_spec`) that cross-checks every dashboard field against the actual DataFrame — this is the primary hallucination-prevention mechanism, not just an LLM self-check. Otherwise it uses an LLM judge call. Bypassed entirely for decline messages, empty results, or when a HITL approval is pending.
- Both `handle_request` (JSON) and `handle_stream_request` (SSE generator, consumed by `/api/chat/stream`) drive the same graph; SSE emits `pev_step`/`plan`/`executing`/`verifying`/`human_approval_required`/`final_response` events consumed by `frontend/components/PEVStepper.tsx`.

### Human-in-the-Loop gate
Mutating `integration_agent` calls and sensitive `db_agent` queries (salary/HR/finance tables) pause execution, store a pending record in `Orchestrator.pending_approvals` (in-memory, keyed by `action_id`), and emit `human_approval_required` over SSE. The frontend must call `POST /api/chat/approve` to resume; `Orchestrator.handle_approval_decision` re-executes with RLS injection (`db_agent.rls_transformer.inject_row_level_security`) for SQL or the MCP REST call for integrations.

### Agent contract & registry
All agents implement `src/agents/base_agent.py::BaseAgent` (`process_request(query, session_id) -> str`, `get_metadata() -> dict`). `src/registry/manager.py::AgentRegistry` is a validation gate, not just a lookup table: on `register()`/`register_async()` it rejects agents whose `description` has >80% cosine (bag-of-words) similarity to an already-registered agent's description (ambiguity prevention for the planner's routing), and runs a functional probe against `process_request` (async version actually invokes it with a timeout; sync version only checks the interface). Keep agent descriptions distinct and non-empty or registration will raise.

Agents live under `src/agents/<name>_agent/agent.py`; `data_agent` additionally has a `sandbox.py` (safe pandas/exec sandboxing for CSV analysis) and its own internal 5-sub-agent swarm (EDA → layout → chart spec → storyteller → quality evaluator) producing the 12-column `dashboard_spec` JSON consumed by `frontend/components/dashboard/`. `db_agent` has `validator.py` (sqlglot AST allow-listing of `SELECT`-only, auto `LIMIT 1000`) and `rls_transformer.py`.

### Shared infrastructure (`src/shared/`)
- `llm_client.py` — unified LiteLLM-backed client with model tiering (`FAST_LLM_MODEL` for planner/verifier/routing, `HEAVY_LLM_MODEL` for synthesis/storytelling) and Langfuse callback wiring.
- `security.py` — prompt-injection scanning (NFKC normalization, zero-width stripping, base64 payload decode, jailbreak pattern matching) at the gateway boundary, nonce-wrapped user input (`wrap_user_input`/`unwrap_user_input`), and canary-token leak detection applied to every outgoing response/SSE event.
- `memory_manager.py` — mem0ai-backed long-term memory, PII redaction (VN phone numbers, CCCD, email, credit card) before persistence.
- `reranker_client.py` — TEI cross-encoder client with a hard circuit-breaker timeout (`RERANKER_TIMEOUT`, default 0.8s) that falls back gracefully.
- `redis_client.py` — session history (max 5 turns) and active-CSV-file caching per session (so `/api/analyze` can be called again without re-uploading).
- `csv_sanitizer.py` — encoding auto-detection + header/row cleanup before any agent sees a CSV.
- `snapshot_manager.py` — semantic-versioned rollback if a quality score regresses >15%.

### Gateway (`src/gateway/main.py`)
FastAPI app; `src/api/gateway.py` is a thin re-export alias to the same `app` (both `uvicorn src.gateway.main:app` and `uvicorn src.api.gateway:app` work — don't duplicate logic there). Key endpoints: `POST /api/chat` (sync JSON), `POST /api/chat/stream` (SSE), `POST /api/chat/approve` (HITL), `POST /api/analyze` (CSV upload/analysis), `POST /api/chat/title`, `GET /health`. Every mutating endpoint runs the prompt-injection scan and canary-leak check inline before/after orchestrator invocation. `src/ui/app.py` is a legacy Streamlit test harness, not the production UI — the production UI is `frontend/`.

### Frontend (`frontend/`)
Next.js 14 App Router. `lib/sse.ts` drives the PEV SSE stream, `lib/duckdb.ts` loads DuckDB-WASM for in-browser SQL over analyzed CSVs (`components/DataSummaryView.tsx` SQL playground), `components/dashboard/DynamicDashboard.tsx` + `EChartComponent.tsx` render the 12-column `dashboard_spec` from the data agent. `components/PEVStepper.tsx` visualizes planner/executor/verifier state from SSE events in real time.

### Config
All settings load through `src/config.py::Settings` (pydantic-settings, reads `.env`). Import as `from src.config import settings` — it's a cached singleton (`get_settings()` via `lru_cache`), not re-instantiated per request.
