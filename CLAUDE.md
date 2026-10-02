# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Enterprise multi-agent system: a FastAPI/LangGraph backend orchestrating 5 specialized agents (RAG, Data Analyst, Search, Database, Integration) behind a Next.js 14 frontend. Core loop is a **PEV (Plan → Execute → Verify)** state machine built on LangGraph, with a strict schema-audit verifier to drive hallucination toward zero. Docs/comments in the codebase are largely Vietnamese; code identifiers are English.

## Commands

### Backend (Python 3.11/3.12)
```bash
python -m venv venv && venv\Scripts\activate     # Windows
pip install -r requirements-dev.txt -c requirements.lock   # runtime deps + pytest + ruff; requirements.lock pins every version (frozen from the Linux image)

# Run backend locally (requires postgres/redis up — see docker-compose)
uvicorn src.gateway.main:app --host 0.0.0.0 --port 8000 --reload

# Ingest sample documents into pgvector (rag_chunks table); run from the project root
python -m scripts.run_ingestion

# Tests — pytest.ini sets testpaths/pythonpath; each file is independent
python -m pytest tests/ -v
python -m pytest tests/test_hardened_upgrades.py -v
python -m pytest tests/test_enterprise_upgrades.py -v
python -m pytest tests/test_architectural_upgrades.py -v
python -m pytest tests/test_audit_and_optimizations.py -v
python -m pytest tests/test_llm_routing_and_planner.py -v
python -m pytest tests/test_zero_trust_security.py -v

# Single test
python -m pytest tests/test_enterprise_upgrades.py::TestClassName::test_name -v

# Offline LLM-as-a-Judge evaluation against golden dataset -> reports/eval_report.json/.md
python scripts/run_offline_eval.py

# Light load test against a running backend (add --chat N for N overlapping chat turns, which cost LLM calls)
python -m scripts.loadtest --users 20 --duration 10

# Database migrations (Alembic; the gateway also applies them at start, AUTO_MIGRATE) and users for the login screen
python -m scripts.migrate --status          # alembic revision -m "..." for a new change; src/ingestion/schema.py is FROZEN (baseline 0001)
python -m scripts.make_user --username alice --roles admin     # prints an AUTH_USERS entry (scrypt hash)

# Several backend replicas behind nginx (separate compose project) and the shared-state check
docker compose -p scaletest -f docker-compose.yml -f docker-compose.scale.yml up -d --scale backend=3 backend lb
python -m scripts.replica_check --base http://127.0.0.1:8100 --expect-replicas 3
```
Tests that need a real PostgreSQL (migrations, conversations, db role/RLS, setup race) skip unless `RAG_TEST_DSN` points to a scratch database (superuser, pgvector); CI sets it.

### Frontend (`frontend/`, Next.js 14 App Router)
```bash
cd frontend
npm install
npm run dev      # port 3000
npm run build
npm run lint
npm test         # vitest unit tests (tests/unit)
npm run test:e2e # Playwright, config at tests/e2e/playwright.config.ts
```

### Full stack via Docker Compose
```bash
docker compose up -d --build   # 7 services: postgres, redis, backend, frontend, langfuse-web/worker, tei-reranker, python-sandbox
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build   # backend hot-reload (mounts ./src)
docker exec agent_backend python -m scripts.run_ingestion                   # load ./dataset into pgvector
```
Ports: frontend `3001`, backend `8000` (Swagger at `/docs`), Langfuse `3005`, TEI reranker `8080`, Postgres `5432`, Redis `6379` (infra ports bound to 127.0.0.1).

`.env` (copy from `.env.example`) must set `OPENROUTER_API_KEY`, plus `POSTGRES_PASSWORD`, `LANGFUSE_NEXTAUTH_SECRET` and `LANGFUSE_SALT` for Compose (no defaults, no secrets in the compose file). `TAVILY_API_KEY` enables `search_agent` web search. Backend image is multi-stage, non-root; build with `INSTALL_BROWSER=false` to skip Chromium.

### Repository layout
`src/` backend package · `frontend/` Next.js app · `tests/` pytest · `scripts/` CLIs (`run_ingestion`, `run_offline_eval`, report tooling; `scripts/dev/` = ad-hoc experiments) · `docs/` all documentation (see `docs/DATA_AGENT_REVIEW_AND_ROADMAP.md`) · `reports/` generated eval output · `dataset/` ingestion documents + golden eval set · `legacy/` retired code (Streamlit UI, old standalone `rag_pipeline`).

## Architecture

### PEV Loop (the core control flow — read this before touching orchestration)
`src/orchestrator/core.py` builds a LangGraph `StateGraph` with three nodes: `planner → executor → verifier`, with a conditional edge back to `executor` on verification failure (max 2 retries, then the response is returned with a warning banner). State shape is `src/orchestrator/state.py` (`AgentState` TypedDict). There is no LangGraph checkpointer (every request builds its whole state; the old `MemorySaver` only accumulated checkpoints in RAM): `handle_stream_request` rebuilds the final state from the nodes' own updates (do NOT call `graph.aget_state`, it raises "No checkpointer set"); conversation context is the Redis history. `tests/test_orchestrator_graph_paths.py` runs the whole graph through both entry points.

- **Planner node**: picks `target_agent` and builds `plan`. Routing precedence: forced `agent_mode` → CSV attached (routes to `data_agent`, with dashboard-vs-text-only decided by keyword heuristics in the query) → compound-query decomposition into parallel DAG sub-tasks (`_decompose_subtasks`, fan-out/fan-in via `asyncio.gather` + LLM synthesis) → LLM planner call (`FAST_LLM_MODEL`) → keyword-based fallback route (`_determine_fallback_route`) if the LLM call fails.
- **Executor node**: resolves the agent via `AgentRegistry.lookup`, injects verifier feedback into the query on retry, and gates two sensitive operations behind **Human-in-the-Loop (HITL) approval** (see below) before calling `agent.process_csv_request` or `agent.process_request`.
- **Verifier node**: for dashboard results, runs a **strict truth audit** (`src/orchestrator/verifier.py::verify_dashboard_spec`): it re-loads the uploaded file (same sampling as the agent), recompiles every chart from its `spec`, recomputes every KPI, and checks that every number in the story and chart insights exists in the fact table. This is the primary hallucination-prevention mechanism; when it passes no LLM judge is called. Other results use an LLM judge call. Bypassed for decline messages, empty results, `type: "error"` replies, or when a HITL approval is pending.
- Both `handle_request` (JSON) and `handle_stream_request` (SSE generator, consumed by `/api/chat/stream`) drive the same graph; SSE emits `pev_step`/`plan`/`executing`/`verifying`/`human_approval_required`/`final_response` events consumed by `frontend/components/PEVStepper.tsx`.

`Orchestrator` (`core.py`: planner/executor/verifier nodes, routing, memory) is assembled from `ApprovalMixin` (`approvals.py`: HITL pending records and the decision handler) and `StreamingMixin` (`streaming.py`: the SSE generator); shared helpers are in `common.py`. While a node is writing an answer, `src/shared/answer_stream.py` (a ContextVar sink attached by `StreamingMixin._stream_with_answer_deltas`) lets the RAG agent push `answer_delta`/`answer_reset` SSE events: a PREVIEW that `final_response` replaces after verification. Parallel sub-answers (DAG) run with streaming suspended; the JSON endpoint never streams.

### Human-in-the-Loop gate
Mutating `integration_agent` calls and sensitive `db_agent` queries (salary/HR/finance tables) pause execution, store a pending record in `Orchestrator.pending_approvals` (in-process fast path, keyed by `action_id`, mirrored in Redis as `hitl:pending:<action_id>` with the approval TTL so it survives restarts and works on any replica; `_claim_pending` lets exactly one caller act on it), and emit `human_approval_required` over SSE. The frontend must call `POST /api/chat/approve` to resume; `Orchestrator.handle_approval_decision` re-executes with RLS injection (`db_agent.rls_transformer.inject_row_level_security`) for SQL or the MCP REST call for integrations.

### Agent contract & registry
All agents implement `src/agents/base_agent.py::BaseAgent` (`process_request(query, session_id) -> str`, `get_metadata() -> dict`). `src/registry/manager.py::AgentRegistry` is a validation gate, not just a lookup table: on `register()`/`register_async()` it rejects agents whose `description` has >80% cosine (bag-of-words) similarity to an already-registered agent's description (ambiguity prevention for the planner's routing), and runs a functional probe against `process_request` (async version actually invokes it with a timeout; sync version only checks the interface). Keep agent descriptions distinct and non-empty or registration will raise.

Agents live under `src/agents/<name>_agent/agent.py`; `data_agent` is a deterministic pipeline of small modules wired by `agent.py`: `ingest` (CSV/TSV/Excel/Parquet/JSON, encodings, currency/percent/date text → typed columns, bounded sample) → `profiler` (value/statistics-based roles, sum-vs-average aggregation policy, time grain, quality) → `insights` (facts that carry numbers only) → `charts` (`ChartSpec` + `compile_chart`, the single place chart data is computed; `plan_dashboard`, `build_kpis`) → `story` (sentences rendered from facts; an LLM may only reword if names and numbers survive) → `verifier`. Follow-up questions go through `qa` (LLM writes pandas → `sandbox` AST allow-list → isolated subprocess). Output is `dashboard_spec` v2 (12-column layout, `story`, `facts`, `kpis`, `charts`, `slicers`, `table`), consumed by `frontend/components/dashboard/`; `POST /api/analyze/filter` recomputes and re-verifies charts for cross-filtering. Only the aggregation lexicon in `profiler.py` looks at column names. `db_agent` has `validator.py` (sqlglot AST allow-listing of `SELECT`-only, auto `LIMIT 1000`) and `rls_transformer.py`; with `DB_AGENT_PASSWORD` set the gateway creates a read-only Postgres role (`src/shared/db_roles.py`: SELECT only on `DB_AGENT_TABLES`, read-only transactions, 15 s statement timeout) and gives the db_agent its own MCP client on that role — the database enforces the boundary even if the validator is bypassed.

### RAG pipeline (`src/agents/rag_agent/`, `src/ingestion/`)
Ingestion (`python -m scripts.run_ingestion [--dataset DIR] [--reset] [--prune]`) is incremental: one document = `doc_key` (`<category>/<filename>`) + `doc_hash`; unchanged files are skipped, changed ones are replaced atomically in one transaction, PDF pages are mapped to chunks (`page`) and repeated headers/footers stripped. The schema lives in `src/ingestion/schema.py` (`ensure_schema` is idempotent and runs at gateway start: new columns, generated `tsv`, HNSW, GIN, drops the redundant ivfflat index). Retrieval (`knowledge.py`): vector top-k (raw and/or HyDE query, `RAG_QUERY_MODE`) + full-text top-k fused with RRF (`RAG_RRF_K`), category filter inferred from the question, a vector-similarity gate (`RAG_MIN_VECTOR_SCORE`), then an optional TEI cross-encoder rerank under a total time budget (`RERANKER_TIMEOUT`; pool `RERANK_POOL_K`, text `MAX_RERANK_TEXT_LENGTH`). Answering (`agent.py`): `planner.py` makes ONE fast-model call that turns the question (+ Redis history for follow-ups) into a standalone question and a HyDE passage (on failure the question is used as typed and the store writes its own HyDE passage); a NOT_FOUND inside a category named in the question is retried once over the whole corpus; sources are fenced in nonce-wrapped envelopes (strong injection signals only are dropped), the LLM must cite `[n]`, and the reply JSON carries `verification{status,grounded,cited,unsupported_numbers}` which the orchestrator turns into a verdict (`_rag_verdict`) — no LLM judge for RAG. Do not put a `.env` override on the rerank keys above unless you re-measure: `python -m scripts.run_rag_eval [--manual|--only-manual] [--rerank] [--answers N] [--min-hit5 X --min-mrr Y]` writes `reports/rag_eval.md/.json` (hit@k, MRR per language / follow-up, rerank latency, refusal separation on cosine and reranker score, answer support; needs the real corpus + TEI; the `--min-*` flags make it a CI gate). `dataset/rag_eval_manual.json` holds hand-written Vietnamese questions (answer = a chunk of the named file containing a phrase; some with chat history). Things already measured and rejected (do not re-add without new evidence): English translation of the query, rerank pool 20, two-stage rerank, per-file cap, neighbour-chunk expansion, cross-document dedup — see `docs/RAG_REVIEW_AND_FIXES.md`. Findings and numbers: `docs/RAG_REVIEW_AND_FIXES.md`.

**Knowledge-base upload from the chat** (`POST /api/knowledge/upload`, `src/ingestion/upload.py`): a PDF/DOCX/PPTX/TXT/MD attached in the chat (`SUPPORTED_EXTENSIONS` in `document_loader.py`; scanned PDFs go through `src/ingestion/ocr.py`: pypdfium2 + Tesseract `vie+eng`, `OCR_*` settings, refused when Tesseract is missing) is loaded by the same `load_document` as the folder ingestion and written through the same `IngestionEmbedder.ingest` (same columns, `doc_key`, prefix, embedding, dedup, atomic replace), so rows are identical to existing ones; only chunking differs: per section, < 200 chars merged with the next, > 600 split into several similar-sized chunks of ≤ 600 (`split_oversized`, nothing is lost; the count is reported as `split`), headingless prose split into ≤ 600 pieces. A copy goes to `<KNOWLEDGE_DIR>/<category>/` so `run_ingestion --prune/--reset` keep it; `KnowledgeStore.invalidate_categories()` makes a new category usable at once; authenticated callers need `KNOWLEDGE_UPLOAD_ROLES`. The folder ingestion keeps its own (measured) chunk sizes: do not make it follow the 200–600 rule without re-running `run_rag_eval`.

**Knowledge-base management** (`src/gateway/knowledge.py`, router `/api/knowledge`): `GET /documents` lists documents (doc_key, chunks, pages), `DELETE /documents?doc_key=` removes one document and its kept copy (`KNOWLEDGE_UPLOAD_ROLES`; `doc_key` is validated against `DOC_KEY` and the file path is checked to stay under `KNOWLEDGE_DIR`), `GET /page?doc_key&page&q` renders a PDF page as PNG with the cited passage highlighted (`src/ingestion/preview.py`: alphanumeric-normalized continuous-span match, header `X-Highlighted`). Replacing a document = uploading the same name. In the chat, `/docs` shows the list (`KnowledgeDocumentsCard`) and sources with a page get a "view page" button (`PageViewer`). **Contextual retrieval** (`src/ingestion/context.py`, `KB_LLM_CONTEXT`, `run_ingestion --llm-context`, `scripts/recontext.py`): an LLM sentence stored as `[Context: …]` at the start of `content` (embedded, in FTS, shown to the answer model; `raw_content` untouched, stripped from citation snippets); see `docs/RAG_REVIEW_AND_FIXES.md` for the measurement before turning it on.

### Shared infrastructure (`src/shared/`)
- `llm_client.py` — unified LiteLLM-backed client with model tiering (`FAST_LLM_MODEL` for planner/verifier/routing, `HEAVY_LLM_MODEL` for synthesis/storytelling) and Langfuse callback wiring; the Langfuse part lives in `tracing.py` (`connect` proves the keys with `auth_check()` before tracing is on and never breaks the app; ONE shared client, each request gets a LangGraph callback on a new trace via `langchain_handler`; `alias_langchain_modules` lets the V2 SDK's handler import under langchain 1.x). Compose provisions the Langfuse org/project/keys/admin from `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_INIT_USER_*` (`LANGFUSE_INIT_*`, only while the Langfuse DB is empty).
- `security.py` — prompt-injection scanning (NFKC normalization, zero-width stripping, base64 payload decode, jailbreak pattern matching) at the gateway boundary, nonce-wrapped user input (`wrap_user_input`/`unwrap_user_input`), and canary-token leak detection applied to every outgoing response/SSE event.
- `memory_manager.py` — mem0ai-backed long-term memory, PII redaction (VN phone numbers, CCCD, email, credit card) before persistence. mem0 is synchronous and each call does LLM/embedding requests: the orchestrator runs it via `Orchestrator._memory_call` (thread + real timeout, write 30 s / read 5 s) and stores the text the user typed (nonce wrapper removed). `MEM0_VECTOR_STORE=pgvector` (set by docker-compose) keeps it in PostgreSQL (`mem0_memories`), so it survives restarts; `memory` (default, tests) is in-process Qdrant. It is keyed by `auth.memory_user_id()` = `<tenant>:<user>` when authenticated, else by session.
- `reranker_client.py` — TEI cross-encoder client with a hard circuit-breaker timeout (`RERANKER_TIMEOUT`, default 0.8s) that falls back gracefully.
- `redis_client.py` — session history (max 5 turns) and active-CSV-file caching per session (so `/api/analyze` can be called again without re-uploading).
- `csv_sanitizer.py` — encoding auto-detection + header/row cleanup before any agent sees a CSV.
- `snapshot_manager.py` — semantic-versioned rollback if a quality score regresses >15%.

**Data/DB infrastructure.** Alembic (`migrations/`, `src/shared/migrations.py`; revision 0001 = `schema.py`, 0002 = `conversations`; advisory locks serialise replicas; one-time setup in `PostgresClient`/`ensure_schema` also takes `SETUP_LOCK_ID`). The db_agent's read-only role also gets Postgres RLS policies (`tenant_scope`, `db_roles._apply_tenant_policy`) and its `MCPClient(scoped=True)` runs each query in a transaction that sets `app.tenant_id`/`app.department_id` (`PostgresClient.fetch_scoped`). LLM-written analysis code runs in the `python-sandbox` container (`sandbox_server.py`, HMAC-signed requests, Parquet not pickle, internal network, fail closed) when `SANDBOX_URL` is set; empty = child process (dev). `src/gateway/conversations.py` is the `/api/conversations` router (per tenant+user, optimistic concurrency on `updated_at`, compared to the millisecond).

### Gateway (`src/gateway/main.py`)
Every `/api/*` route depends on `src/shared/auth.py::authenticate` (`AUTH_MODE=off` = anonymous dev user; `jwt` = Bearer token, HS256 secret or JWKS). The resulting `Principal` scopes the session key (`Principal.session()` → `<user>:<client session id>`, used for Redis history, cached files, LangGraph thread and HITL approvals; responses still return the client's own id), supplies tenant/department to RLS via `current_scope()` (a contextvar; RLS is `department_id = … AND tenant_id = …` and the db_agent fails closed if it cannot be applied) and gates `POST /api/chat/approve` by `HITL_APPROVER_ROLES`. `src/shared/rate_limit.py` limits chat/analyze per user or IP (Redis fixed windows, fails open); `/api/analyze` rejects oversized uploads from `Content-Length` and reads in chunks; `GET /ready` checks Postgres/Redis/reranker (503 only when Postgres, Redis or the orchestrator is down), `GET /health` is liveness only. Mint dev tokens with `python -m scripts.make_token --user alice --roles approver`.
FastAPI app; `src/api/gateway.py` is a thin re-export alias to the same `app` (both `uvicorn src.gateway.main:app` and `uvicorn src.api.gateway:app` work — don't duplicate logic there). Key endpoints: `POST /api/chat` (sync JSON), `POST /api/chat/stream` (SSE), `POST /api/chat/approve` (HITL), `POST /api/analyze` (CSV upload/analysis), `POST /api/chat/title`, `GET /health`. Every mutating endpoint runs the prompt-injection scan and canary-leak check inline before/after orchestrator invocation. `legacy/streamlit_ui/app.py` is a legacy Streamlit test harness, not the production UI — the production UI is `frontend/`.

### Frontend (`frontend/`)
Next.js 14 App Router. `lib/sse.ts` drives the PEV SSE stream, `lib/duckdb.ts` loads DuckDB-WASM for in-browser SQL over analyzed CSVs (`components/DataSummaryView.tsx` SQL playground), `components/dashboard/DynamicDashboard.tsx` + `EChartComponent.tsx` render the 12-column `dashboard_spec` v2 from the data agent (no client-side re-aggregation: `lib/chartOption.ts` only draws server numbers, `lib/dashboardApi.ts` calls the filter endpoint). Unit tests: `npm test` (vitest, `tests/unit/`). `components/PEVStepper.tsx` visualizes planner/executor/verifier state from SSE events in real time (the state transitions are pure functions in `lib/pevTrace.ts`). Auth: `app/login` + `app/api/auth/*` keep the JWT from `POST /api/auth/login` in an httpOnly cookie, and every route handler under `app/api/**` turns it into the Bearer header (`lib/backendAuth.ts::authHeaders`; the generic `/api/*` rewrite does NOT do that, so any new authenticated route needs its own handler). A document attached in `ChatInterface` goes to `/api/knowledge/upload` instead of the chat; `/docs` lists/deletes knowledge-base documents. Signed-in users' conversations sync with `/api/conversations` (`lib/conversationSync.ts` pure plan + `lib/useConversationSync.ts`; the browser copy is cleared on sign-out). ALL interface text (vi/en) lives in `lib/locales/vi.ts` (the key contract) + `en.ts` and is read with `t(lang, key, vars)` / `useLang()` from `lib/i18n.ts` (`getLang()` outside React); never write Vietnamese or English UI text inline: `tests/unit/i18nCoverage.test.ts` fails on a missing key, mismatched `{placeholders}` or Vietnamese literals in `app/`, `components/`, `lib/` (a short allow-list for regexes that parse backend text). `lib/apiFetch.ts` adds `X-UI-Lang` so the backend (`src/shared/messages.py`, `msg(key)`) answers errors in the same language; route handlers use `lib/serverMessages.ts`. Node descriptions in the PEV stepper come from the dictionaries, the backend's `logs`/`message` text is not shown. Dashboards use `lib/uiText.ts` (language of the data).

### Config
All settings load through `src/config.py::Settings` (pydantic-settings, reads `.env`). Import as `from src.config import settings` — it's a cached singleton (`get_settings()` via `lru_cache`), not re-instantiated per request.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
