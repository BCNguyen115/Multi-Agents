# Graph Report - multi_agent_mvp  (2026-10-02)

## Corpus Check
- 229 files · ~201,824 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 18 file(s) not represented in the graph (top: (none) 9, .ini 2, .example 1)

## Summary
- 3360 nodes · 7501 edges · 168 communities (98 shown, 70 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 335 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `67faea28`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- RAGAgent
- Enterprise_Multi_Agent_System_Technical_Documentation_1e82f236.md
- test_adversarial_datasets.py
- typing
- test_story.py
- RESTToolInput
- ChatPage
- data_agent/agent.py
- security.py
- lifespan
- KnowledgeStore
- SnapshotManager
- SafePythonSandbox
- TestSQLValidatorHardening
- Orchestrator
- DynamicDashboard.tsx
- pytest
- ._attempt
- gateway/main.py
- test_charts.py
- CLAUDE.md project guide
- MockAgent
- Project review and roadmap (2026-09-30)
- TestIntentRoutingAndDataAgent
- test_kb_manage.py
- test_enterprise_upgrades.py
- ChatInterface.tsx
- app/page.tsx
- dependencies
- normalize_model_name
- ChatMessage.tsx
- RAG Agent review and fixes
- test_readiness.py
- PostgresClient
- RedisClient
- package.json
- ._executor_node
- migrations.py
- _quality
- verify_internal_token
- charts.py
- profile_dataframe_universal
- .handle_stream_request
- Principal
- README (Enterprise Multi-Agent System)
- redact_pii
- test_tracing.py
- profiler.py
- next
- test_kb_upload.py
- insights.py
- verify_dashboard_spec
- IngestionEmbedder
- compilerOptions
- PEV Loop self-correcting cycle
- Enterprise autonomous AI architecture whitepaper
- qa.py
- scenario
- dataset_reader.py
- Data Agent review and roadmap
- FakeRedis
- DocumentChunk
- test_hitl_shared_state.py
- ingestion/document_loader.py
- SecurityASTVisitor
- test_kb_context.py
- test_ssrf_guards.py
- requirements.txt runtime dependencies
- LLMClient
- msg
- TestCSVSanitizerHardening
- numbers_grounded
- BaseAgent
- core.py
- test_sandbox_security.py
- test_reranker_scoring.py
- test_conversations.py
- test_db_roles.py
- TestEnterpriseUpgrades
- test_login.py
- test_rag_store.py
- TestPillar1DirectInjectionAndNonce
- Universalization refactor report
- MCPClient
- upload_knowledge
- _validate_semver
- test_hitl_and_routing.py
- backend service (FastAPI + PEV orchestrator)
- validate_sql
- conversations.py
- test_auth.py
- TestModelTieringConfig
- test_rate_limit.py
- AnswerStream
- EmptyDescAgent
- test_answer_streaming.py
- backend job (pytest + ruff + pgvector service)
- wrap_user_input
- react
- test_agent_memory.py
- TestPillar3SQLASTGuardAndParameterization
- DualList
- test_insights.py
- test_rag_agent.py
- coerce_types
- upload.py
- Dataset
- ._planner_node
- AgentSnapshot
- TestSQLGuardrails
- EmptyNameAgent
- DatabaseAgent
- TestRAGAgentFallback
- inject_row_level_security
- .process_request
- ApprovalMixin
- validate_auth_config
- .eslintrc.json
- next.config.mjs
- test_rag_eval_gate.py
- PEVStepper.tsx
- FPT brand (Vietnamese technology corporation)
- _compute_cosine_similarity
- test_out.docx conversion (empty table)
- scenario
- ocr_pdf_pages
- test_sandbox_remote.py
- conversationSync.test.ts
- current_scope
- issue_login_token
- make_handler
- SandboxResult
- ensure_readonly_role
- MalformedMetadataAgent
- reject_oversized_uploads
- i18nCoverage.test.ts
- TestInfrastructureConfig
- SyncProcessAgent
- FakePipeline
- test_ingestion.py
- TestOrchestratorForcedRouting
- run_ingestion

## God Nodes (most connected - your core abstractions)
1. `Orchestrator` - 64 edges
2. `AgentRegistry` - 58 edges
3. `LLMClient` - 55 edges
4. `DataAnalystAgent` - 52 edges
5. `RAGAgent` - 50 edges
6. `get_logger()` - 48 edges
7. `profile_dataframe_universal()` - 47 edges
8. `PostgresClient` - 41 edges
9. `verify_dashboard_spec()` - 40 edges
10. `Principal` - 39 edges

## Surprising Connections (you probably didn't know these)
- `Ingest-Profile-Insight-Plan-Compile-Verify-Narrate pipeline` --semantically_similar_to--> `data_agent deterministic pipeline (ingest-profiler-insights-charts-story-verifier)`  [INFERRED] [semantically similar]
  docs/DATA_AGENT_REVIEW_AND_ROADMAP.md → CLAUDE.md
- `CSV summary chat: 5,000 rows x 27 columns (ai_ds_job_salaries_2026.csv)` --references--> `data_agent deterministic pipeline (ingest-profiler-insights-charts-story-verifier)`  [INFERRED]
  frontend/public/Multi-Agent Enterprise System.pdf → CLAUDE.md
- `Text-to-analysis Q&A in AST-allow-listed sandbox` --semantically_similar_to--> `qa text-to-pandas with AST-allow-listed sandbox`  [INFERRED] [semantically similar]
  docs/DATA_AGENT_REVIEW_AND_ROADMAP.md → CLAUDE.md
- `Verifier recomputes charts/KPIs from uploaded file` --semantically_similar_to--> `Verifier node (strict truth audit)`  [INFERRED] [semantically similar]
  docs/DATA_AGENT_REVIEW_AND_ROADMAP.md → CLAUDE.md
- `Advanced RAG (HyDE, hybrid, TEI reranker)` --semantically_similar_to--> `RAG Agent`  [INFERRED] [semantically similar]
  graphify-out/converted/MULTI_AGENT_ENTERPRISE_SYSTEM_REPORT_8eb5cfe3.md → README.md

## Import Cycles
- 3-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/agents/data_agent/charts.py -> src/agents/data_agent/__init__.py`
- 3-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/orchestrator/verifier.py -> src/agents/data_agent/__init__.py`
- 3-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/agents/data_agent/insights.py -> src/agents/data_agent/__init__.py`
- 4-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/orchestrator/verifier.py -> src/agents/data_agent/charts.py -> src/agents/data_agent/__init__.py`
- 4-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/agents/data_agent/charts.py -> src/agents/data_agent/insights.py -> src/agents/data_agent/__init__.py`
- 4-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/orchestrator/verifier.py -> src/agents/data_agent/insights.py -> src/agents/data_agent/__init__.py`
- 4-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/agents/data_agent/story.py -> src/agents/data_agent/insights.py -> src/agents/data_agent/__init__.py`
- 5-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/orchestrator/verifier.py -> src/agents/data_agent/charts.py -> src/agents/data_agent/insights.py -> src/agents/data_agent/__init__.py`
- 5-file cycle: `src/agents/data_agent/__init__.py -> src/agents/data_agent/agent.py -> src/orchestrator/verifier.py -> src/agents/data_agent/story.py -> src/agents/data_agent/insights.py -> src/agents/data_agent/__init__.py`

## Hyperedges (group relationships)
- **RAG planner-retrieve-rerank-cite flow** — docs_rag_review_and_fixes_planner_one_call, docs_rag_review_and_fixes_hybrid_rrf_retrieval, docs_rag_review_and_fixes_rerank_budget, docs_rag_review_and_fixes_deterministic_rag_verifier [EXTRACTED 0.85]
- **Code-computed verified dashboard pipeline** — docs_data_agent_review_and_roadmap_ingest_layer, docs_data_agent_review_and_roadmap_profiler_v2, docs_data_agent_review_and_roadmap_insight_engine, docs_data_agent_review_and_roadmap_planner_spec_compiler, docs_data_agent_review_and_roadmap_verified_storytelling [EXTRACTED 0.90]
- **HyDE + hybrid search + reranker retrieval chain** — readme_hyde, readme_hybrid_search, readme_tei_reranker, readme_circuit_breaker [EXTRACTED 0.90]
- **Specialized agents swarm in whitepaper** — graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_data_analyst_swarm, graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_advanced_rag, graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_web_search_agent, graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_db_and_integration_agents [EXTRACTED 0.90]
- **Zero-Trust 5-pillar injection defense** — graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_nonce_wrapping, graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_data_spotlighting, graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_sql_ast_firewall, graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_mcp_command_injection_control, graphify_out_converted_multi_agent_enterprise_system_report_8eb5cfe3_canary_honeypot [EXTRACTED 0.90]
- **PEV loop planner-executor-verifier cycle** — claude_planner_node, claude_executor_node, claude_verifier_node [EXTRACTED 0.95]
- **Five specialized agents orchestrated by PEV** — readme_rag_agent, readme_data_agent, readme_search_agent, readme_database_agent, readme_integration_agent [EXTRACTED 0.95]
- **Controls that depend on real user identity** — docs_project_review_and_roadmap_auth_identity, docs_project_review_and_roadmap_hitl_approver_audit, docs_project_review_and_roadmap_tenant_rls_and, docs_project_review_and_roadmap_mem0_bugs [INFERRED 0.85]

## Communities (168 total, 70 thin omitted)

### Community 0 - "RAGAgent"
Cohesion: 0.18
Nodes (25): RAGAgent, ask(), chunk(), FakeLLM, FakeStore, prompt_of(), test_a_broad_topic_is_summarised_not_refused_by_the_prompt_rules(), test_a_chunk_or_label_cannot_close_the_untrusted_envelope() (+17 more)

### Community 1 - "Enterprise_Multi_Agent_System_Technical_Documentation_1e82f236.md"
Cohesion: 0.05
Nodes (41): 10.1 Hạn chế, 10.2 Lộ trình, 10. Lộ trình và hạn chế đã biết, 1.1 Bối cảnh và vấn đề, 1.2 Mục tiêu kinh doanh, 1.3 Người dùng mục tiêu, 1.4 Thành tựu chính, 1. Tóm tắt điều hành (+33 more)

### Community 2 - "test_adversarial_datasets.py"
Cohesion: 0.06
Nodes (43): _all_null_and_constant(), ask(), _bom_utf8(), _boolean_flags(), _categorical_only(), _csv(), _currency_and_percent(), _dates_only() (+35 more)

### Community 3 - "typing"
Cohesion: 0.06
Nodes (7): _remove_diacritics(), sanitize_columns(), _slug(), get_logger(), JsonFormatter, SessionFilter, setup_root_logger()

### Community 4 - "test_story.py"
Cohesion: 0.07
Nodes (40): _column_details(), _escape_cell(), agg_phrase(), format_pct(), grain_word(), tr(), _trim(), annotate_charts() (+32 more)

### Community 5 - "RESTToolInput"
Cohesion: 0.13
Nodes (4): RESTToolInput, SQLToolInput, test_the_allow_list_comes_from_configuration(), TestPillar4MCPToolValidation

### Community 6 - "ChatPage"
Cohesion: 0.06
Nodes (4): ChatPage, DashboardPage, SidebarPage, @playwright/test

### Community 7 - "data_agent/agent.py"
Cohesion: 0.07
Nodes (17): test_pipeline(), main(), main(), _Analysis, _column_type(), DataAnalystAgent, _json_safe(), _table_rows() (+9 more)

### Community 8 - "security.py"
Cohesion: 0.05
Nodes (11): parameterize_sql(), chat(), _detect_base64_injection(), generate_canary_token(), generate_input_nonce(), inspect_prompt_safety(), inspect_response_for_canary_leak(), _normalize_for_safety_check() (+3 more)

### Community 9 - "lifespan"
Cohesion: 0.18
Nodes (4): test_async(), test(), lifespan(), MemoryManager

### Community 10 - "KnowledgeStore"
Cohesion: 0.09
Nodes (6): fuse(), KnowledgeStore, QueryPlan, test_a_plan_supplies_the_hyde_passage_without_another_llm_call(), test_fusion_ranks_by_agreement_and_keeps_the_best_scores(), test_without_a_passage_in_the_plan_the_store_writes_its_own()

### Community 14 - "Orchestrator"
Cohesion: 0.07
Nodes (9): get_settings(), Settings, Orchestrator, AgentRegistry, TestDAGParallelExecution, TestHumanInTheLoopGate, TestPlannerHardeningAndFallbackRoutes, _run() (+1 more)

### Community 15 - "DynamicDashboard.tsx"
Cohesion: 0.05
Nodes (22): DashboardView(), DynamicDashboardProps, KPI_ICONS, KpiCard(), OTHER_LABELS, pct(), SPAN, DARK_PALETTE (+14 more)

### Community 18 - "gateway/main.py"
Cohesion: 0.05
Nodes (25): analyze_csv(), chat_approve(), chat_stream(), remember_turn(), safe_stream_wrapper(), filter_dashboard(), generate_chat_title(), login() (+17 more)

### Community 19 - "test_charts.py"
Cohesion: 0.11
Nodes (17): _norm(), parse_query_hints(), _compile(), test_correlation_heatmap_has_unit_diagonal_and_symmetry(), test_crosstab_heatmap(), test_donut_shares_add_up_and_small_slices_become_other(), test_heavy_tailed_histogram_clips_and_says_so(), test_histogram_counts_every_value() (+9 more)

### Community 20 - "CLAUDE.md project guide"
Cohesion: 0.07
Nodes (32): AgentRegistry validation gate, BaseAgent contract, CLAUDE.md project guide, dashboard_spec v2 (12-column layout), data_agent deterministic pipeline (ingest-profiler-insights-charts-story-verifier), db_agent sqlglot validator + RLS transformer, Docker Compose stack (7 services), Executor node (+24 more)

### Community 21 - "MockAgent"
Cohesion: 0.08
Nodes (6): MockAgent, TestRegistryAsyncProbe, _run(), _run(), _run(), TestRegistryValidationGate

### Community 22 - "Project review and roadmap (2026-09-30)"
Cohesion: 0.09
Nodes (31): Bearer JWT auth and user-bound sessions, DevOps and repo hygiene findings, Frontend findings (two chat-history sources, oversized components, unused libs), HITL approver role and audit log, mem0 memory bugs (empty, blocking loop, non-durable), mem0 fix: asyncio.to_thread, real user text, pgvector, MemorySaver removed, Project review and roadmap (2026-09-30) (+23 more)

### Community 24 - "test_kb_manage.py"
Cohesion: 0.05
Nodes (31): _extract_docx_text(), _extract_pptx_text(), load_and_analyze_documents(), load_document(), ingest_upload(), _load(), safe_filename(), UploadError (+23 more)

### Community 25 - "test_enterprise_upgrades.py"
Cohesion: 0.06
Nodes (10): print_fail(), print_header(), print_pass(), run_comprehensive_tests(), _apply_limits(), _jsonable(), run_untrusted(), _safe_import() (+2 more)

### Community 26 - "ChatInterface.tsx"
Cohesion: 0.08
Nodes (11): AgentDropdown(), ChatInput(), ChatInputProps, ChatInterfaceProps, CSVUploaderProps, Three-phase action plan, Auto-scroll jitter during SSE streaming (ChatInterface), ChatInput dual-mount state collision (+3 more)

### Community 27 - "app/page.tsx"
Cohesion: 0.09
Nodes (17): HomePage(), ChatInterface(), CommandItem, CommandPalette(), CommandPaletteProps, SearchView(), SearchViewProps, ChatItem() (+9 more)

### Community 28 - "dependencies"
Cohesion: 0.07
Nodes (27): dependencies, ag-grid-community, ag-grid-react, clsx, @duckdb/duckdb-wasm, echarts, echarts-for-react, lucide-react (+19 more)

### Community 30 - "ChatMessage.tsx"
Cohesion: 0.18
Nodes (16): ApprovalCard(), ChatMessage(), ChatMessageProps, extractWebSourcesFromMarkdown(), hasDashboardIntent(), isDataAgentTarget(), DashboardSkeleton(), DynamicDashboard() (+8 more)

### Community 31 - "RAG Agent review and fixes"
Cohesion: 0.16
Nodes (19): Incremental ingestion (doc_key + doc_hash), RAG pipeline (hybrid retrieval + rerank + cited answer), run_rag_eval measurement gate, TEI cross-encoder reranker, Cosine threshold RAG_MIN_VECTOR_SCORE=0.30, Removed .env overrides of rerank keys, Nonce-wrapped source envelopes, strong-signal injection filter, Incremental hash-based ingestion with page mapping (+11 more)

### Community 32 - "test_readiness.py"
Cohesion: 0.09
Nodes (9): health_check(), _probe(), readiness(), ready(), test_a_hanging_dependency_cannot_hang_the_probe(), test_a_missing_reranker_is_degraded_but_still_serves(), test_everything_up_is_ready(), test_not_ready_until_the_orchestrator_is_built() (+1 more)

### Community 33 - "PostgresClient"
Cohesion: 0.12
Nodes (9): readonly_dsn(), PostgresClient, test_postgres_itself_refuses_everything_outside_the_allow_list(), scenario(), test_postgres_itself_separates_rows_by_tenant_and_department_even_without_a_where_clause(), scenario(), test_the_role_dsn_keeps_host_port_and_database_and_encodes_the_password(), test_four_replicas_starting_on_an_empty_database_all_succeed() (+1 more)

### Community 35 - "package.json"
Cohesion: 0.08
Nodes (24): name, private, scripts, build, dev, lint, start, test (+16 more)

### Community 37 - "migrations.py"
Cohesion: 0.07
Nodes (10): run_migrations_offline(), run_migrations_online(), alembic_config(), current_revision(), database_url(), head_revision(), upgrade_to_head(), test_the_driver_url_is_psycopg_and_keeps_credentials_host_and_options() (+2 more)

### Community 39 - "verify_internal_token"
Cohesion: 0.11
Nodes (6): generate_internal_token(), _get_jwt_secret(), _urlsafe_b64decode(), _urlsafe_b64encode(), verify_internal_token(), TestJWTSecurity

### Community 40 - "charts.py"
Cohesion: 0.11
Nodes (32): _agg_of(), build_kpis(), measure_card(), ChartContext, ChartSpec, _compile_heatmap(), _compile_histogram(), _compile_rank() (+24 more)

### Community 41 - "profile_dataframe_universal"
Cohesion: 0.11
Nodes (24): load_dataset(), safe_read_csv(), choose_time_grain(), is_monetary_name(), profile_dataframe_universal(), _frame(), test_aggregation_policy_uses_sum_only_with_additivity_evidence(), test_any_common_delimiter_is_read_as_columns() (+16 more)

### Community 43 - "Principal"
Cohesion: 0.13
Nodes (8): limit_analyze(), limit_chat(), _who(), whoami(), Principal, caller_key(), enforce(), _local_count()

### Community 44 - "README (Enterprise Multi-Agent System)"
Cohesion: 0.09
Nodes (25): Vector + full-text RRF fusion, RAG planner stops translating Vietnamese to English, Hybrid vector + FTS retrieval with RRF, tsv GIN index, Planner: one LLM call for standalone question + HyDE, Advanced RAG (HyDE, hybrid, TEI reranker), 7 microservices matrix, pypdf + python-docx, faiss-cpu vector store (+17 more)

### Community 46 - "test_tracing.py"
Cohesion: 0.15
Nodes (15): alias_langchain_modules(), connect(), langchain_handler(), with_trace(), _fake_langfuse(), _restore_litellm_callbacks(), _settings(), test_a_handler_failure_only_skips_tracing_for_that_request() (+7 more)

### Community 47 - "profiler.py"
Cohesion: 0.12
Nodes (21): agg_policy(), classify_column_role(), _classify_numeric(), _classify_text(), _dimension_score(), _infer_dayfirst(), is_identifier_column(), _is_sequence() (+13 more)

### Community 48 - "next"
Cohesion: 0.06
Nodes (28): dynamic, maxDuration, dynamic, maxDuration, dynamic, dynamic, dynamic, dynamic (+20 more)

### Community 49 - "test_kb_upload.py"
Cohesion: 0.11
Nodes (27): Section, build_upload_chunks(), merge_short_sections(), _paragraph_sections(), split_oversized(), test_every_chunk_of_a_document_gets_its_own_call_and_only_content_changes(), test_a_markdown_upload_is_stored_like_any_other_document(), test_markdown_is_split_at_its_headings_and_keeps_vietnamese() (+19 more)

### Community 50 - "insights.py"
Cohesion: 0.17
Nodes (19): _agg_of(), _anomalies(), _clip(), _composition(), _contribution(), _correlations(), _distribution(), generate_insights() (+11 more)

### Community 51 - "verify_dashboard_spec"
Cohesion: 0.11
Nodes (24): compile_chart(), auto_remediate_chart_specs(), _chart_column_errors(), _close(), _profile_from_spec(), _suggest(), _values_match(), verify_dashboard_spec() (+16 more)

### Community 52 - "IngestionEmbedder"
Cohesion: 0.07
Nodes (14): DocumentChunk, _cosine_similarity_matrix(), _doc_key(), _find_duplicates(), IngestionEmbedder, _chunk(), FakeConn, FakeOpenAI (+6 more)

### Community 53 - "compilerOptions"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 54 - "PEV Loop self-correcting cycle"
Cohesion: 0.14
Nodes (14): Canary honeypot tokens, Data Analyst swarm (5 sub-agents), Data spotlighting envelopes for untrusted sources, MCP and command-injection control (Pydantic v2, whitelist, HITL), Dynamic nonce wrapping of user input, SQL AST firewall (sqlglot, RLS, parameterization), 5-pillar Zero-Trust injection hardening, Data Analyst Agent (5 sub-agent swarm) (+6 more)

### Community 55 - "Enterprise autonomous AI architecture whitepaper"
Cohesion: 0.13
Nodes (19): Engineering changelog, Database and Integration agents via MCP, Key .env variables, 4-layer enterprise framework, Strategic roadmap (streaming dashboard, multimodal, RBAC/SSO), Internal JWT and PII redaction, Memory layer (Redis window + Mem0), Offline LLM-as-a-Judge evaluation (+11 more)

### Community 56 - "qa.py"
Cohesion: 0.05
Nodes (19): answer_question(), _build_prompt(), _cell(), _clean(), extract_code(), _narrate(), _normalise_table(), QAResult (+11 more)

### Community 57 - "scenario"
Cohesion: 0.21
Nodes (11): bearer(), test_input_is_validated_before_anything_touches_the_database(), scenario(), TestAgainstPostgres, go(), scenario(), scenario(), scenario() (+3 more)

### Community 58 - "dataset_reader.py"
Cohesion: 0.14
Nodes (12): _extract_plain_text(), _clean(), DatasetReadError, decode_bytes(), _detect_format(), _read_csv_text(), _read_excel(), _read_json() (+4 more)

### Community 59 - "Data Agent review and roadmap"
Cohesion: 0.16
Nodes (16): Data Agent review and roadmap, Findings B: not generalizing (delimiter, non-Latin names, name-based rules), Findings D: indirect prompt injection, payload duplication, Findings C: no insight engine, unverified story, Findings E: technical debt, Findings A: wrong numbers (NaN to 0, SUM everywhere), Phase 1-4 implementation status, Ingest layer (multi-format, encoding, DuckDB) (+8 more)

### Community 60 - "FakeRedis"
Cohesion: 0.12
Nodes (8): FakeLLM, FakeRedis, make_client(), settle(), test_a_failing_summary_never_breaks_the_turn(), go(), test_history_is_capped_at_five_turns_and_the_dropped_ones_are_summarised(), go()

### Community 61 - "DocumentChunk"
Cohesion: 0.08
Nodes (9): DocumentChunk, _cosine_similarity_matrix(), create_embeddings_model(), deduplicate_chunks(), embed_and_deduplicate(), embed_chunks(), _find_duplicates(), HyDERetriever (+1 more)

### Community 62 - "test_hitl_shared_state.py"
Cohesion: 0.27
Nodes (10): decide(), FakeRedisClient, raise_approval(), replica(), test_a_wrong_session_neither_decides_nor_consumes_the_approval(), test_an_approval_raised_on_one_replica_can_be_decided_on_another(), test_an_approval_survives_a_restart(), test_only_what_approving_needs_goes_to_redis_with_the_approval_ttl() (+2 more)

### Community 63 - "ingestion/document_loader.py"
Cohesion: 0.05
Nodes (20): _generate_walkthrough(), main(), _build_contextual_prefix(), chunk_documents(), _fallback_chunk(), _merge_small_sections(), _split_oversized_section(), _detect_best_pattern() (+12 more)

### Community 65 - "test_kb_context.py"
Cohesion: 0.13
Nodes (13): apply_context(), _clean(), contextualize(), contextualize_chunks(), one(), generate_context(), FakeLLM, test_a_failing_model_costs_nothing_but_the_context() (+5 more)

### Community 66 - "test_ssrf_guards.py"
Cohesion: 0.20
Nodes (10): _is_internal_host(), resolves_to_private_address(), call(), client_with(), fake_dns(), test_a_public_address_is_let_through(), test_an_allowed_name_that_resolves_to_a_private_address_is_refused_without_sending_anything(), test_an_unresolvable_name_is_refused() (+2 more)

### Community 67 - "requirements.txt runtime dependencies"
Cohesion: 0.13
Nodes (16): Legacy Streamlit UI requirements, plotly, streamlit + streamlit-aggrid, asyncpg PostgreSQL driver, chardet encoding detection, crawl4ai (needs Chromium), pandas + numpy, pypdf + python-docx (+8 more)

### Community 68 - "LLMClient"
Cohesion: 0.08
Nodes (9): main(), main(), test(), LLMClient, disable_telemetry(), TestLLMClientFallbackAndAliases, _run(), _run() (+1 more)

### Community 69 - "msg"
Cohesion: 0.12
Nodes (12): delete_document(), DeleteResult, describe_upload(), _file_path(), KnowledgeDocument, list_documents(), page_image(), _pg() (+4 more)

### Community 70 - "TestCSVSanitizerHardening"
Cohesion: 0.06
Nodes (3): sanitize_column_names(), detect_and_convert_encoding(), TestCSVSanitizerHardening

### Community 71 - "numbers_grounded"
Cohesion: 0.18
Nodes (8): collect_evidence(), extract_numbers(), numbers_grounded(), _walk(), _fact(), test_labels_with_digits_are_names_not_claims(), test_number_formatting_round_trips_through_grounding(), test_number_grounding()

### Community 72 - "BaseAgent"
Cohesion: 0.09
Nodes (3): BaseAgent, IntegrationAgent, unwrap_user_input()

### Community 73 - "core.py"
Cohesion: 0.06
Nodes (10): extract_data_metrics(), test_regex(), _build_pev_trace(), _initial_state(), build_planner_prompt(), build_routing_system_prompt(), build_routing_user_prompt(), build_verifier_prompt() (+2 more)

### Community 75 - "test_reranker_scoring.py"
Cohesion: 0.05
Nodes (20): _is_circuit_open(), _record_failure(), _record_success(), rerank_documents(), _score(), _first_working(), truncate_text(), payload() (+12 more)

### Community 76 - "test_conversations.py"
Cohesion: 0.19
Nodes (9): ConversationIn, _newer_than(), client_for(), jwt_mode(), message(), test_a_conversation_body_limits_the_number_of_messages(), test_an_oversized_conversation_is_refused(), scenario() (+1 more)

### Community 77 - "test_db_roles.py"
Cohesion: 0.30
Nodes (9): RecordingPg, run(), test_a_second_run_alters_instead_of_creating_and_missing_tables_are_skipped(), test_a_short_password_is_refused(), test_a_table_with_tenant_columns_gets_a_row_level_security_policy_for_the_role_only(), test_a_table_without_tenant_columns_gets_no_policy_but_stays_granted(), test_names_and_passwords_cannot_inject_sql(), test_the_policy_uses_only_the_columns_the_table_has_and_is_recreated_on_every_start() (+1 more)

### Community 79 - "test_login.py"
Cohesion: 0.12
Nodes (15): authenticate_user(), hash_password(), login_enabled(), verify_password(), gateway(), request(), sign_in(), test_login_needs_jwt_mode_a_shared_secret_and_users() (+7 more)

### Community 80 - "test_rag_store.py"
Cohesion: 0.22
Nodes (5): build_tsquery(), detect_categories(), ensure_schema(), test_categories_named_in_the_question_are_detected_as_whole_words(), test_tsquery_is_an_or_of_distinct_words_and_cannot_be_injected()

### Community 82 - "Universalization refactor report"
Cohesion: 0.12
Nodes (20): Planner and ChartSpec compiler, buildUniversalQuery with aggregation allow-list (duckdb.ts), Light-mode contrast (>=7:1) accent/foreground tokens, CSS design tokens replacing hex colors in EChartComponent, formatUniversalMetric in formatters.ts, Remaining limits (monetary-name list, src/src duplicates), Removed hardcoded column/dataset names and SEMANTIC_MEASURE_PRIORITY, Universal profiler (values not names): temporal_columns, is_monetary_name (+12 more)

### Community 84 - "upload_knowledge"
Cohesion: 0.15
Nodes (7): upload_knowledge(), call(), FakeFile, FakePG, test_endpoint_refuses_callers_without_the_knowledge_role_and_bad_files(), test_endpoint_size_limit_and_middleware_cover_the_new_route(), test_endpoint_stores_the_document_and_describes_it_in_chat_words()

### Community 86 - "test_hitl_and_routing.py"
Cohesion: 0.14
Nodes (16): ui_language(), current_lang(), pick_lang(), reset_lang(), set_lang(), _decide(), orch(), _pending() (+8 more)

### Community 87 - "backend service (FastAPI + PEV orchestrator)"
Cohesion: 0.33
Nodes (11): backend service (FastAPI + PEV orchestrator), Backend hot-reload (uvicorn --reload, ./src mount), docker-compose.dev.yml hot-reload override, docker-compose.yml production-like stack, frontend service (Next.js 14), langfuse-web service, langfuse-worker service, postgres service (pgvector image) (+3 more)

### Community 89 - "conversations.py"
Cohesion: 0.27
Nodes (10): _check_id(), Conversation, ConversationSummary, delete_conversation(), _full(), get_conversation(), list_conversations(), _pg() (+2 more)

### Community 90 - "test_auth.py"
Cohesion: 0.29
Nodes (11): get(), test_a_token_without_subject_or_expiry_is_refused(), test_a_valid_token_identifies_the_user_and_scopes_the_session_and_sql(), test_an_unsigned_token_is_refused(), test_audience_and_issuer_are_verified_when_configured(), test_missing_bad_or_expired_tokens_are_refused(), test_only_approver_roles_may_approve(), test_only_the_configured_algorithm_is_accepted() (+3 more)

### Community 92 - "test_rate_limit.py"
Cohesion: 0.44
Nodes (9): call(), FakeRedis, request(), test_a_limit_of_zero_or_a_missing_redis_means_unlimited(), test_anonymous_callers_are_told_apart_by_ip(), test_calls_up_to_the_limit_pass_and_the_next_is_refused_with_retry_after(), test_each_user_and_each_route_group_has_its_own_budget(), test_the_counter_expires_by_itself() (+1 more)

### Community 93 - "AnswerStream"
Cohesion: 0.13
Nodes (7): AnswerStream, attach(), current(), detach(), suspended(), test_only_one_writer_at_a_time_so_parallel_answers_do_not_interleave(), test_suspended_blocks_turn_streaming_off_for_their_duration()

### Community 95 - "test_answer_streaming.py"
Cohesion: 0.14
Nodes (19): agent(), chunks(), drained(), generate_with_sink(), orchestrator(), RecordingAgent, run_stream(), StreamingLLM (+11 more)

### Community 96 - "backend job (pytest + ruff + pgvector service)"
Cohesion: 0.27
Nodes (10): backend job (pytest + ruff + pgvector service), GitHub Actions CI workflow, frontend job (lint, tsc, vitest, build), images job (docker build, INSTALL_BROWSER=false), pgvector/pgvector:pg16 test database, requirements.lock pinned dependencies, CI workflow and dependency lock, pytest (+2 more)

### Community 97 - "wrap_user_input"
Cohesion: 0.23
Nodes (12): wrap_user_input(), test_the_orchestrator_reads_and_writes_memory_under_the_users_id(), scenario(), test_the_user_text_is_stored_without_the_nonce_wrapper(), scenario(), collect(), orchestrator(), run_stream() (+4 more)

### Community 98 - "react"
Cohesion: 0.10
Nodes (17): metadata, RootLayout(), AgentSelectorInChatProps, AgentThoughtStepperProps, ApprovalCardProps, Header(), HeaderProps, KnowledgeDoc (+9 more)

### Community 99 - "test_agent_memory.py"
Cohesion: 0.09
Nodes (12): DualResult, vector_store_config(), make(), SlowMemory, test_a_slow_memory_write_does_not_freeze_the_event_loop(), scenario(), write(), test_a_write_that_times_out_or_fails_never_raises() (+4 more)

### Community 102 - "test_insights.py"
Cohesion: 0.08
Nodes (23): aggregate_values(), as_datetime(), group_aggregate(), _partial_flags(), days(), period_label(), period_series(), trim_partial() (+15 more)

### Community 103 - "test_rag_agent.py"
Cohesion: 0.17
Nodes (8): unsupported_numbers(), QueryPlanner, FakeRedis, test_a_vietnamese_question_is_never_replaced_by_an_english_rewrite(), test_citation_and_list_markers_are_not_mistaken_for_numbers(), test_one_planning_call_per_question_and_no_chat_when_there_is_no_history(), test_planner_output_is_sanitised_and_cached(), test_source_numbers_written_in_prose_are_not_claims()

### Community 104 - "coerce_types"
Cohesion: 0.33
Nodes (3): coerce_types(), _normalise_number_text(), _to_numeric_column()

### Community 105 - "upload.py"
Cohesion: 0.10
Nodes (10): _build_contextual_prefix(), _fallback_chunk(), _merge_small_sections(), _page_of(), _split_oversized_section(), ChunkReport, infer_category(), safe_category() (+2 more)

### Community 107 - "._planner_node"
Cohesion: 0.15
Nodes (3): store(), memory_user_id(), test_memory_belongs_to_the_authenticated_user_else_to_the_session()

### Community 115 - ".process_request"
Cohesion: 0.22
Nodes (3): _citations(), test_the_citation_snippet_shows_the_document_text_not_the_generated_context(), test_citation_numbers_that_do_not_exist_are_ignored()

### Community 118 - "validate_auth_config"
Cohesion: 0.25
Nodes (7): _looks_like_placeholder(), validate_auth_config(), test_jwt_mode_will_not_start_with_a_missing_weak_or_placeholder_secret(), test_jwt_mode_will_not_start_with_the_placeholder_internal_secret(), test_jwt_mode_will_not_start_without_the_analysis_sandbox(), test_valid_and_off_configurations_start(), test_startup_refuses_a_user_list_with_plain_text_passwords()

### Community 123 - "test_rag_eval_gate.py"
Cohesion: 0.32
Nodes (3): gate(), test_a_drop_beyond_max_drop_against_the_baseline_fails_even_above_the_minimum(), test_without_a_baseline_only_the_minimums_apply()

### Community 125 - "PEVStepper.tsx"
Cohesion: 0.29
Nodes (3): getAgentPipelineSteps(), PEVStepper(), PEVStepperProps

### Community 141 - "scenario"
Cohesion: 0.29
Nodes (4): _one_hot(), test_migration_search_filters_and_fallbacks_on_a_real_database(), scenario(), TopicLLM

### Community 142 - "ocr_pdf_pages"
Cohesion: 0.33
Nodes (4): _languages(), ocr_available(), ocr_pdf_pages(), test_ocr_reports_itself_unavailable_when_switched_off()

### Community 143 - "test_sandbox_remote.py"
Cohesion: 0.21
Nodes (11): serve(), remote(), server(), test_a_frame_parquet_cannot_hold_is_reported_not_crashed(), test_a_remote_run_gives_the_same_answer_as_a_local_one(), test_a_wrong_secret_is_rejected_by_the_service(), test_dates_and_text_survive_the_trip_as_parquet(), test_the_service_clamps_the_limits_a_caller_asks_for() (+3 more)

### Community 146 - "current_scope"
Cohesion: 0.33
Nodes (5): current_scope(), client(), who(), test_authentication_off_keeps_the_single_anonymous_user(), who()

### Community 147 - "issue_login_token"
Cohesion: 0.43
Nodes (5): _decode(), issue_login_token(), _principal_from_claims(), test_issued_token_is_accepted_by_the_same_checks_every_api_call_uses(), test_tokens_expire()

### Community 148 - "make_handler"
Cohesion: 0.21
Nodes (7): make_handler(), do_GET(), do_POST(), _reply(), run_request(), sign_request(), test_requests_without_a_valid_signature_get_401_and_garbage_does_not_kill_the_server()

### Community 150 - "ensure_readonly_role"
Cohesion: 0.33
Nodes (4): _apply_tenant_policy(), ensure_readonly_role(), _identifier(), _literal()

### Community 158 - "test_ingestion.py"
Cohesion: 0.11
Nodes (17): chunk_documents(), _detect_best_pattern(), _extract_pdf(), _extract_pdf_text(), _join_pages(), _line_key(), SectionedDocument, _split_into_sections() (+9 more)

### Community 159 - "TestOrchestratorForcedRouting"
Cohesion: 0.40
Nodes (3): TestOrchestratorForcedRouting, _run(), _run()

### Community 161 - "run_ingestion"
Cohesion: 0.29
Nodes (3): main(), run_ingestion(), _write_report()

## Knowledge Gaps
- **210 isolated node(s):** `extends`, `next/core-web-vitals`, `maxDuration`, `dynamic`, `maxDuration` (+205 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1369 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **70 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `validate_sql()` connect `validate_sql` to `.test_insert_rejected`, `typing`, `.test_truncate_rejected`, `.test_simple_select_passes`, `.test_auto_inject_limit`, `.test_whitespace_only_rejected`, `security.py`, `core.py`, `TestPillar3SQLASTGuardAndParameterization`, `.test_revoke_rejected`, `TestSQLGuardrails`, `TestSQLValidatorHardening`, `DatabaseAgent`, `.test_drop_table_rejected`, `.test_alter_rejected`, `.test_multi_statement_rejected`, `.test_grant_rejected`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `RAGAgent` connect `RAGAgent` to `test_kb_context.py`, `typing`, `LLMClient`, `test_rag_agent.py`, `BaseAgent`, `lifespan`, `KnowledgeStore`, `core.py`, `._attempt`, `gateway/main.py`, `.process_request`, `TestRAGAgentFallback`, `test_answer_streaming.py`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `LLMClient` connect `LLMClient` to `RAGAgent`, `run_ingestion`, `PostgresClient`, `typing`, `data_agent/agent.py`, `BaseAgent`, `lifespan`, `KnowledgeStore`, `core.py`, `Orchestrator`, `DatabaseAgent`, `test_tracing.py`, `._attempt`, `gateway/main.py`, `MCPClient`, `qa.py`, `normalize_model_name`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `Orchestrator` (e.g. with `lifespan()` and `BaseAgent`) actually correct?**
  _`Orchestrator` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `AgentRegistry` (e.g. with `TestEnterpriseUpgrades` and `lifespan()`) actually correct?**
  _`AgentRegistry` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `LLMClient` (e.g. with `DataAnalystAgent` and `DatabaseAgent`) actually correct?**
  _`LLMClient` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `extends`, `next/core-web-vitals`, `maxDuration` to the rest of the system?**
  _210 weakly-connected nodes found - possible documentation gaps or missing edges._