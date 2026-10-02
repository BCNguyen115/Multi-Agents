# Graph Report - multi_agent_mvp  (2026-10-01)

## Corpus Check
- 222 files · ~178,940 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 18 file(s) not represented in the graph (top: (none) 9, .ini 2, .example 1)

## Summary
- 3260 nodes · 7338 edges · 151 communities (93 shown, 58 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 332 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `67faea28`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_rag_agent.py
- test_insights.py
- test_adversarial_datasets.py
- typing
- test_story.py
- test_ssrf_guards.py
- ChatPage
- data_agent/agent.py
- inspect_prompt_safety
- lifespan
- KnowledgeStore
- SnapshotManager
- SafePythonSandbox
- TestSQLValidatorHardening
- Orchestrator
- DynamicDashboard.tsx
- security.py
- RAGAgent
- gateway/main.py
- test_charts.py
- CLAUDE.md project guide
- MockAgent
- Project review and roadmap (2026-09-30)
- ._planner_node
- test_kb_manage.py
- asyncio
- ChatInterface.tsx
- app/page.tsx
- dependencies
- test_agent_e2e.py
- ChatMessage.tsx
- RAG Agent review and fixes
- test_readiness.py
- .ingest
- RedisClient
- package.json
- ._executor_node
- test_migrations.py
- profile_dataframe_universal
- verify_internal_token
- charts.py
- test_ingest_and_profiler.py
- .handle_stream_request
- parameterize_sql
- README (Enterprise Multi-Agent System)
- redact_pii
- test_tracing.py
- profiler.py
- next
- test_kb_upload.py
- insights.py
- verify_dashboard_spec
- test_ingestion.py
- compilerOptions
- PEV Loop self-correcting cycle
- Enterprise autonomous AI architecture whitepaper
- qa.py
- ingest_upload
- read_table
- Data Agent review and roadmap
- HyDERetriever
- src/embedder.py
- test_hitl_shared_state.py
- dataclasses
- SecurityASTVisitor
- test_kb_context.py
- _fallback_chunk
- requirements.txt runtime dependencies
- LLMClient
- gateway/knowledge.py
- TestCSVSanitizerHardening
- SearchAgent
- unwrap_user_input
- core.py
- test_sandbox_security.py
- test_reranker_scoring.py
- sandbox.py
- test_db_roles.py
- test_upgrades_validation.py
- test_auth.py
- PostgresClient
- TestPillar1DirectInjectionAndNonce
- Universalization refactor report
- MCPClient
- DualResult
- test_enterprise_upgrades.py
- test_hitl_and_routing.py
- backend service (FastAPI + PEV orchestrator)
- validate_sql
- msg
- prompt_templates.py
- TestModelTieringConfig
- test_rate_limit.py
- AnswerStream
- EmptyDescAgent
- StreamingLLM
- backend job (pytest + ruff + pgvector service)
- test_orchestrator_graph_paths.py
- react
- wrap_user_input
- TestPillar3SQLASTGuardAndParameterization
- DualList
- numpy
- unsupported_numbers
- coerce_types
- upload.py
- Dataset
- devDependencies
- chunks
- TestSQLGuardrails
- EmptyNameAgent
- TestRAGAgentFallback
- inject_row_level_security
- .eslintrc.json
- next.config.mjs
- FPT brand (Vietnamese technology corporation)
- _compute_cosine_similarity
- test_out.docx conversion (empty table)
- test_sandbox_remote.py
- conversationSync.test.ts
- rag_pipeline/main.py
- test_answer_streaming.py
- make_handler
- SandboxResult
- main
- i18nCoverage.test.ts
- ingestion/document_loader.py
- run_ingestion
- setup_root_logger

## God Nodes (most connected - your core abstractions)
1. `Orchestrator` - 61 edges
2. `AgentRegistry` - 58 edges
3. `LLMClient` - 55 edges
4. `DataAnalystAgent` - 52 edges
5. `RAGAgent` - 50 edges
6. `profile_dataframe_universal()` - 47 edges
7. `get_logger()` - 47 edges
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
- `LangGraph PEV loop (Plan-Execute-Verify)` --semantically_similar_to--> `PEV Loop (Plan-Execute-Verify) state machine`  [INFERRED] [semantically similar]
  graphify-out/converted/MULTI_AGENT_ENTERPRISE_SYSTEM_REPORT_8eb5cfe3.md → CLAUDE.md

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

## Communities (151 total, 58 thin omitted)

### Community 0 - "test_rag_agent.py"
Cohesion: 0.15
Nodes (29): QueryPlanner, ask(), chunk(), FakeLLM, FakeRedis, FakeStore, prompt_of(), test_a_broad_topic_is_summarised_not_refused_by_the_prompt_rules() (+21 more)

### Community 1 - "test_insights.py"
Cohesion: 0.21
Nodes (11): _by_kind(), test_anomalous_month_is_flagged(), test_categorical_only_data_uses_record_counts(), test_composition_reports_the_dominant_category(), test_contribution_names_the_planted_driver(), test_correlated_pair_is_found_and_flagged_as_not_causal(), test_generation_is_deterministic(), test_significant_group_difference_is_found() (+3 more)

### Community 2 - "test_adversarial_datasets.py"
Cohesion: 0.09
Nodes (26): _all_null_and_constant(), ask(), _bom_utf8(), _boolean_flags(), _categorical_only(), _csv(), _currency_and_percent(), _dates_only() (+18 more)

### Community 3 - "typing"
Cohesion: 0.06
Nodes (3): sanitize_columns(), _slug(), get_logger()

### Community 4 - "test_story.py"
Cohesion: 0.06
Nodes (43): collect_evidence(), extract_numbers(), numbers_grounded(), _walk(), format_number(), format_pct(), _trim(), annotate_charts() (+35 more)

### Community 5 - "test_ssrf_guards.py"
Cohesion: 0.07
Nodes (14): _is_internal_host(), resolves_to_private_address(), RESTToolInput, SQLToolInput, call(), client_with(), fake_dns(), test_a_public_address_is_let_through() (+6 more)

### Community 6 - "ChatPage"
Cohesion: 0.06
Nodes (4): ChatPage, DashboardPage, SidebarPage, @playwright/test

### Community 7 - "data_agent/agent.py"
Cohesion: 0.06
Nodes (21): main(), test_pipeline(), main(), main(), _Analysis, _column_details(), _column_type(), DataAnalystAgent (+13 more)

### Community 8 - "inspect_prompt_safety"
Cohesion: 0.08
Nodes (5): _detect_base64_injection(), inspect_prompt_safety(), _normalize_for_safety_check(), _semantic_intent_classification(), TestPromptInjectionScanner

### Community 9 - "lifespan"
Cohesion: 0.09
Nodes (5): test_async(), test(), DatabaseAgent, lifespan(), MemoryManager

### Community 10 - "KnowledgeStore"
Cohesion: 0.09
Nodes (6): fuse(), KnowledgeStore, QueryPlan, test_a_plan_supplies_the_hyde_passage_without_another_llm_call(), test_fusion_ranks_by_agreement_and_keeps_the_best_scores(), test_without_a_passage_in_the_plan_the_store_writes_its_own()

### Community 11 - "SnapshotManager"
Cohesion: 0.06
Nodes (3): AgentSnapshot, SnapshotManager, TestSnapshotManager

### Community 14 - "Orchestrator"
Cohesion: 0.08
Nodes (10): get_settings(), Settings, Orchestrator, AgentRegistry, TestDAGParallelExecution, TestHumanInTheLoopGate, orch(), TestPlannerHardeningAndFallbackRoutes (+2 more)

### Community 15 - "DynamicDashboard.tsx"
Cohesion: 0.06
Nodes (20): DashboardView(), DynamicDashboardProps, KPI_ICONS, KpiCard(), OTHER_LABELS, pct(), SPAN, DARK_PALETTE (+12 more)

### Community 16 - "security.py"
Cohesion: 0.11
Nodes (6): generate_canary_token(), generate_input_nonce(), inspect_response_for_canary_leak(), _urlsafe_b64decode(), _urlsafe_b64encode(), TestPillar5CanaryTokensAndAdversarialEval

### Community 17 - "RAGAgent"
Cohesion: 0.11
Nodes (5): _header(), _looks_like_injection(), _neutralize(), RAGAgent, test_the_citation_snippet_shows_the_document_text_not_the_generated_context()

### Community 18 - "gateway/main.py"
Cohesion: 0.04
Nodes (35): analyze_csv(), chat(), chat_approve(), chat_stream(), remember_turn(), safe_stream_wrapper(), filter_dashboard(), generate_chat_title() (+27 more)

### Community 19 - "test_charts.py"
Cohesion: 0.11
Nodes (20): compile_chart(), _norm(), parse_query_hints(), _compile(), test_averaged_measures_are_never_summed_in_planned_charts(), test_correlation_heatmap_has_unit_diagonal_and_symmetry(), test_crosstab_heatmap(), test_donut_shares_add_up_and_small_slices_become_other() (+12 more)

### Community 20 - "CLAUDE.md project guide"
Cohesion: 0.08
Nodes (30): AgentRegistry validation gate, BaseAgent contract, CLAUDE.md project guide, dashboard_spec v2 (12-column layout), data_agent deterministic pipeline (ingest-profiler-insights-charts-story-verifier), db_agent sqlglot validator + RLS transformer, Docker Compose stack (7 services), Executor node (+22 more)

### Community 21 - "MockAgent"
Cohesion: 0.05
Nodes (8): MalformedMetadataAgent, MockAgent, SyncProcessAgent, TestRegistryAsyncProbe, _run(), _run(), _run(), TestRegistryValidationGate

### Community 22 - "Project review and roadmap (2026-09-30)"
Cohesion: 0.09
Nodes (31): Bearer JWT auth and user-bound sessions, DevOps and repo hygiene findings, Frontend findings (two chat-history sources, oversized components, unused libs), HITL approver role and audit log, mem0 memory bugs (empty, blocking loop, non-durable), mem0 fix: asyncio.to_thread, real user text, pgvector, MemorySaver removed, Project review and roadmap (2026-09-30) (+23 more)

### Community 23 - "._planner_node"
Cohesion: 0.07
Nodes (5): store(), build_planner_prompt(), memory_user_id(), TestIntentRoutingAndDataAgent, test_dashboard_intent_helper()

### Community 24 - "test_kb_manage.py"
Cohesion: 0.07
Nodes (29): load_and_analyze_documents(), load_document(), SectionedDocument, _load(), client(), FakePg, make_pptx(), scanned_pdf() (+21 more)

### Community 25 - "asyncio"
Cohesion: 0.10
Nodes (7): print_fail(), print_header(), print_pass(), run_comprehensive_tests(), extract_data_metrics(), test_regex(), _passthrough_dec()

### Community 26 - "ChatInterface.tsx"
Cohesion: 0.08
Nodes (14): Light-mode contrast (>=7:1) accent/foreground tokens, CSS design tokens replacing hex colors in EChartComponent, AgentDropdown(), ChatInput(), ChatInputProps, ChatInterfaceProps, Three-phase action plan, Auto-scroll jitter during SSE streaming (ChatInterface) (+6 more)

### Community 27 - "app/page.tsx"
Cohesion: 0.09
Nodes (18): HomePage(), ChatInterface(), CommandItem, CommandPalette(), CommandPaletteProps, Header(), SearchView(), SearchViewProps (+10 more)

### Community 28 - "dependencies"
Cohesion: 0.13
Nodes (15): dependencies, ag-grid-community, ag-grid-react, clsx, @duckdb/duckdb-wasm, echarts, echarts-for-react, lucide-react (+7 more)

### Community 29 - "test_agent_e2e.py"
Cohesion: 0.12
Nodes (18): safe_read_csv(), agent(), csv_text(), FakeLLM, run(), test_a_tampered_spec_is_caught_by_the_audit(), test_dashboard_is_verified_and_self_consistent(), test_excel_upload_end_to_end() (+10 more)

### Community 30 - "ChatMessage.tsx"
Cohesion: 0.13
Nodes (18): ApprovalCard(), ChatMessage(), ChatMessageProps, extractWebSourcesFromMarkdown(), hasDashboardIntent(), isDataAgentTarget(), DashboardSkeleton(), DynamicDashboard() (+10 more)

### Community 31 - "RAG Agent review and fixes"
Cohesion: 0.12
Nodes (25): Incremental ingestion (doc_key + doc_hash), RAG pipeline (hybrid retrieval + rerank + cited answer), Vector + full-text RRF fusion, run_rag_eval measurement gate, TEI cross-encoder reranker, RAG planner stops translating Vietnamese to English, Cosine threshold RAG_MIN_VECTOR_SCORE=0.30, Removed .env overrides of rerank keys (+17 more)

### Community 32 - "test_readiness.py"
Cohesion: 0.09
Nodes (9): health_check(), _probe(), readiness(), ready(), test_a_hanging_dependency_cannot_hang_the_probe(), test_a_missing_reranker_is_degraded_but_still_serves(), test_everything_up_is_ready(), test_not_ready_until_the_orchestrator_is_built() (+1 more)

### Community 33 - ".ingest"
Cohesion: 0.12
Nodes (3): _cosine_similarity_matrix(), _doc_key(), _find_duplicates()

### Community 35 - "package.json"
Cohesion: 0.07
Nodes (30): DataSummaryProps, DataSummaryView(), extractDataMetrics(), parseMetricsFromMarkdown(), name, private, scripts, build (+22 more)

### Community 37 - "test_migrations.py"
Cohesion: 0.06
Nodes (25): run_migrations_offline(), run_migrations_online(), alembic_config(), current_revision(), database_url(), head_revision(), upgrade_to_head(), bearer() (+17 more)

### Community 38 - "profile_dataframe_universal"
Cohesion: 0.13
Nodes (12): profile_dataframe_universal(), _quality(), world(), test_profile_of_tiny_and_degenerate_tables_does_not_crash(), test_year_columns_are_ordinal_not_measures(), test_no_time_axis_means_no_time_insights(), test_tiny_and_empty_inputs_do_not_crash(), test_an_ordinal_column_is_not_counted_as_an_entity() (+4 more)

### Community 39 - "verify_internal_token"
Cohesion: 0.13
Nodes (4): generate_internal_token(), _get_jwt_secret(), verify_internal_token(), TestJWTSecurity

### Community 40 - "charts.py"
Cohesion: 0.12
Nodes (30): _agg_of(), build_kpis(), measure_card(), ChartContext, ChartSpec, _compile_heatmap(), _compile_histogram(), _compile_rank() (+22 more)

### Community 41 - "test_ingest_and_profiler.py"
Cohesion: 0.14
Nodes (18): load_dataset(), is_monetary_name(), sniff_delimiter(), _frame(), test_aggregation_policy_uses_sum_only_with_additivity_evidence(), test_any_common_delimiter_is_read_as_columns(), test_duplicate_and_blank_headers_get_unique_ids_and_labels(), test_empty_uploads_raise_a_clear_error() (+10 more)

### Community 44 - "README (Enterprise Multi-Agent System)"
Cohesion: 0.10
Nodes (22): Advanced RAG (HyDE, hybrid, TEI reranker), 7 microservices matrix, pypdf + python-docx, faiss-cpu vector store, langchain family, Legacy RAG pipeline requirements, tiktoken, Reranker circuit breaker (800ms) (+14 more)

### Community 46 - "test_tracing.py"
Cohesion: 0.15
Nodes (15): alias_langchain_modules(), connect(), langchain_handler(), with_trace(), _fake_langfuse(), _restore_litellm_callbacks(), _settings(), test_a_handler_failure_only_skips_tracing_for_that_request() (+7 more)

### Community 47 - "profiler.py"
Cohesion: 0.10
Nodes (24): agg_policy(), choose_time_grain(), classify_column_role(), _classify_numeric(), _classify_text(), _dimension_score(), _infer_dayfirst(), is_identifier_column() (+16 more)

### Community 48 - "next"
Cohesion: 0.06
Nodes (28): dynamic, maxDuration, dynamic, maxDuration, dynamic, dynamic, dynamic, dynamic (+20 more)

### Community 49 - "test_kb_upload.py"
Cohesion: 0.09
Nodes (26): infer_category(), merge_short_sections(), safe_category(), call(), docx_bytes(), FakeEmbedder, FakeFile, FakePG (+18 more)

### Community 50 - "insights.py"
Cohesion: 0.17
Nodes (18): _agg_of(), _anomalies(), _clip(), _composition(), _contribution(), _correlations(), _distribution(), generate_insights() (+10 more)

### Community 51 - "verify_dashboard_spec"
Cohesion: 0.14
Nodes (23): auto_remediate_chart_specs(), _chart_column_errors(), _close(), _profile_from_spec(), _suggest(), _values_match(), verify_dashboard_spec(), _bar() (+15 more)

### Community 52 - "test_ingestion.py"
Cohesion: 0.09
Nodes (20): _detect_best_pattern(), _split_into_sections(), _strip_repeated_lines(), IngestionEmbedder, _chunk(), _document(), FakeConn, FakeOpenAI (+12 more)

### Community 53 - "compilerOptions"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 54 - "PEV Loop self-correcting cycle"
Cohesion: 0.12
Nodes (16): AgentState TypedDict schema, Canary honeypot tokens, Data Analyst swarm (5 sub-agents), Data spotlighting envelopes for untrusted sources, MCP and command-injection control (Pydantic v2, whitelist, HITL), Dynamic nonce wrapping of user input, LangGraph PEV loop (Plan-Execute-Verify), SQL AST firewall (sqlglot, RLS, parameterization) (+8 more)

### Community 55 - "Enterprise autonomous AI architecture whitepaper"
Cohesion: 0.13
Nodes (19): Engineering changelog, Database and Integration agents via MCP, Key .env variables, 4-layer enterprise framework, Strategic roadmap (streaming dashboard, multimodal, RBAC/SSO), Internal JWT and PII redaction, Memory layer (Redis window + Mem0), Offline LLM-as-a-Judge evaluation (+11 more)

### Community 56 - "qa.py"
Cohesion: 0.11
Nodes (13): answer_question(), _build_prompt(), _cell(), _clean(), extract_code(), _narrate(), _normalise_table(), QAResult (+5 more)

### Community 57 - "ingest_upload"
Cohesion: 0.21
Nodes (6): ingest_upload(), safe_filename(), _save_copy(), UploadError, test_upload_accepts_the_new_extensions_and_names_them_in_the_error(), test_filenames_are_reduced_to_a_safe_base_name_and_the_type_is_checked()

### Community 58 - "read_table"
Cohesion: 0.23
Nodes (8): _clean(), DatasetReadError, _detect_format(), _read_csv_text(), _read_excel(), _read_json(), read_table(), ReadMeta

### Community 59 - "Data Agent review and roadmap"
Cohesion: 0.16
Nodes (16): Data Agent review and roadmap, Findings B: not generalizing (delimiter, non-Latin names, name-based rules), Findings D: indirect prompt injection, payload duplication, Findings C: no insight engine, unverified story, Findings E: technical debt, Findings A: wrong numbers (NaN to 0, SUM everywhere), Phase 1-4 implementation status, Ingest layer (multi-format, encoding, DuckDB) (+8 more)

### Community 61 - "src/embedder.py"
Cohesion: 0.19
Nodes (6): _cosine_similarity_matrix(), create_embeddings_model(), deduplicate_chunks(), embed_and_deduplicate(), embed_chunks(), _find_duplicates()

### Community 62 - "test_hitl_shared_state.py"
Cohesion: 0.27
Nodes (10): decide(), FakeRedisClient, raise_approval(), replica(), test_a_wrong_session_neither_decides_nor_consumes_the_approval(), test_an_approval_raised_on_one_replica_can_be_decided_on_another(), test_an_approval_survives_a_restart(), test_only_what_approving_needs_goes_to_redis_with_the_approval_ttl() (+2 more)

### Community 63 - "dataclasses"
Cohesion: 0.12
Nodes (10): chunk_documents(), _merge_small_sections(), _split_oversized_section(), _detect_best_pattern(), _extract_docx_text(), _extract_pdf_text(), load_and_analyze_documents(), Section (+2 more)

### Community 65 - "test_kb_context.py"
Cohesion: 0.14
Nodes (14): apply_context(), _clean(), contextualize(), contextualize_chunks(), one(), generate_context(), FakeLLM, test_a_failing_model_costs_nothing_but_the_context() (+6 more)

### Community 67 - "requirements.txt runtime dependencies"
Cohesion: 0.13
Nodes (16): Legacy Streamlit UI requirements, plotly, streamlit + streamlit-aggrid, asyncpg PostgreSQL driver, chardet encoding detection, crawl4ai (needs Chromium), pandas + numpy, pypdf + python-docx (+8 more)

### Community 68 - "LLMClient"
Cohesion: 0.06
Nodes (9): main(), test(), LLMClient, normalize_model_name(), TestLLMClientFallbackAndAliases, _run(), _run(), _run() (+1 more)

### Community 69 - "gateway/knowledge.py"
Cohesion: 0.09
Nodes (14): delete_document(), DeleteResult, _file_path(), KnowledgeDocument, list_documents(), page_image(), _pg(), _alnum() (+6 more)

### Community 70 - "TestCSVSanitizerHardening"
Cohesion: 0.06
Nodes (5): clean_csv_content(), _remove_diacritics(), sanitize_column_names(), detect_and_convert_encoding(), TestCSVSanitizerHardening

### Community 73 - "core.py"
Cohesion: 0.05
Nodes (9): BaseAgent, _build_pev_trace(), _initial_state(), AgentState, TestDockerSandboxAndExportConfig, TestGoldenDatasetExpansion, TestOrchestratorForcedRouting, _run() (+1 more)

### Community 75 - "test_reranker_scoring.py"
Cohesion: 0.06
Nodes (14): _is_circuit_open(), _record_failure(), _record_success(), rerank_documents(), _score(), truncate_text(), TestRerankerCircuitBreaker, _run() (+6 more)

### Community 76 - "sandbox.py"
Cohesion: 0.18
Nodes (5): _apply_limits(), _jsonable(), run_untrusted(), _safe_import(), main()

### Community 77 - "test_db_roles.py"
Cohesion: 0.12
Nodes (19): _apply_tenant_policy(), ensure_readonly_role(), _identifier(), _literal(), readonly_dsn(), RecordingPg, run(), test_a_second_run_alters_instead_of_creating_and_missing_tables_are_skipped() (+11 more)

### Community 79 - "test_auth.py"
Cohesion: 0.06
Nodes (38): authenticate_user(), _decode(), hash_password(), issue_login_token(), login_enabled(), _looks_like_placeholder(), validate_auth_config(), verify_password() (+30 more)

### Community 80 - "PostgresClient"
Cohesion: 0.06
Nodes (12): build_tsquery(), detect_categories(), ensure_schema(), PostgresClient, _one_hot(), test_categories_named_in_the_question_are_detected_as_whole_words(), test_migration_search_filters_and_fallbacks_on_a_real_database(), scenario() (+4 more)

### Community 82 - "Universalization refactor report"
Cohesion: 0.19
Nodes (13): Planner and ChartSpec compiler, buildUniversalQuery with aggregation allow-list (duckdb.ts), formatUniversalMetric in formatters.ts, Remaining limits (monetary-name list, src/src duplicates), Removed hardcoded column/dataset names and SEMANTIC_MEASURE_PRIORITY, Universal profiler (values not names): temporal_columns, is_monetary_name, tests/test_universal_profiler.py, Universalization refactor report (+5 more)

### Community 83 - "MCPClient"
Cohesion: 0.18
Nodes (4): current_scope(), MCPClient, test_authentication_off_keeps_the_single_anonymous_user(), who()

### Community 84 - "DualResult"
Cohesion: 0.17
Nodes (3): DualResult, vector_store_config(), test_the_memory_store_is_chosen_by_configuration()

### Community 86 - "test_hitl_and_routing.py"
Cohesion: 0.33
Nodes (7): _decide(), _pending(), test_expired_approval_is_purged(), test_no_fallback_to_another_action_of_same_session(), test_other_session_cannot_decide(), test_the_graph_keeps_no_per_session_checkpoints(), test_unknown_decision_is_not_approve()

### Community 87 - "backend service (FastAPI + PEV orchestrator)"
Cohesion: 0.33
Nodes (11): backend service (FastAPI + PEV orchestrator), Backend hot-reload (uvicorn --reload, ./src mount), docker-compose.dev.yml hot-reload override, docker-compose.yml production-like stack, frontend service (Next.js 14), langfuse-web service, langfuse-worker service, postgres service (pgvector image) (+3 more)

### Community 89 - "msg"
Cohesion: 0.08
Nodes (26): _check_id(), Conversation, ConversationIn, ConversationSummary, delete_conversation(), _full(), get_conversation(), list_conversations() (+18 more)

### Community 92 - "test_rate_limit.py"
Cohesion: 0.24
Nodes (10): call(), FakePipeline, FakeRedis, request(), test_a_limit_of_zero_or_a_missing_redis_means_unlimited(), test_anonymous_callers_are_told_apart_by_ip(), test_calls_up_to_the_limit_pass_and_the_next_is_refused_with_retry_after(), test_each_user_and_each_route_group_has_its_own_budget() (+2 more)

### Community 93 - "AnswerStream"
Cohesion: 0.13
Nodes (7): AnswerStream, attach(), current(), detach(), suspended(), test_only_one_writer_at_a_time_so_parallel_answers_do_not_interleave(), test_suspended_blocks_turn_streaming_off_for_their_duration()

### Community 95 - "StreamingLLM"
Cohesion: 0.27
Nodes (10): agent(), drained(), generate_with_sink(), StreamingLLM, test_a_not_found_refusal_is_held_back_and_never_shown(), test_a_retry_after_the_verifier_rejected_the_answer_resets_the_preview(), test_if_streaming_fails_before_the_first_token_the_answer_still_comes_blocking(), test_text_that_only_starts_like_the_refusal_is_released_once_it_diverges() (+2 more)

### Community 96 - "backend job (pytest + ruff + pgvector service)"
Cohesion: 0.27
Nodes (10): backend job (pytest + ruff + pgvector service), GitHub Actions CI workflow, frontend job (lint, tsc, vitest, build), images job (docker build, INSTALL_BROWSER=false), pgvector/pgvector:pg16 test database, requirements.lock pinned dependencies, CI workflow and dependency lock, pytest (+2 more)

### Community 97 - "test_orchestrator_graph_paths.py"
Cohesion: 0.43
Nodes (6): orchestrator(), run_stream(), collect(), test_the_final_state_does_not_depend_on_a_checkpointer(), test_the_json_entry_point_runs_the_whole_graph(), test_the_sse_entry_point_runs_the_whole_graph_and_ends_with_the_final_response()

### Community 98 - "react"
Cohesion: 0.10
Nodes (12): metadata, RootLayout(), AgentSelectorInChatProps, AgentThoughtStepperProps, ApprovalCardProps, CSVUploaderProps, HeaderProps, KnowledgeDoc (+4 more)

### Community 99 - "wrap_user_input"
Cohesion: 0.12
Nodes (16): wrap_user_input(), make(), SlowMemory, test_a_slow_memory_write_does_not_freeze_the_event_loop(), scenario(), write(), test_a_write_that_times_out_or_fails_never_raises(), test_async_test_doubles_are_still_awaited() (+8 more)

### Community 102 - "numpy"
Cohesion: 0.13
Nodes (9): aggregate_values(), as_datetime(), _partial_flags(), days(), period_label(), period_series(), trim_partial(), test_missing_values_are_ignored_not_zeroed() (+1 more)

### Community 103 - "unsupported_numbers"
Cohesion: 0.17
Nodes (5): _citations(), unsupported_numbers(), test_citation_and_list_markers_are_not_mistaken_for_numbers(), test_citation_numbers_that_do_not_exist_are_ignored(), test_source_numbers_written_in_prose_are_not_claims()

### Community 104 - "coerce_types"
Cohesion: 0.33
Nodes (3): coerce_types(), _normalise_number_text(), _to_numeric_column()

### Community 105 - "upload.py"
Cohesion: 0.11
Nodes (13): _build_contextual_prefix(), chunk_documents(), DocumentChunk, _fallback_chunk(), _merge_small_sections(), _page_of(), _split_oversized_section(), Section (+5 more)

### Community 107 - "devDependencies"
Cohesion: 0.17
Nodes (12): devDependencies, autoprefixer, eslint, eslint-config-next, @playwright/test, postcss, tailwindcss, @types/node (+4 more)

### Community 116 - "inject_row_level_security"
Cohesion: 0.15
Nodes (3): inject_row_level_security(), ApprovalMixin, TestRowLevelSecurityAST

### Community 143 - "test_sandbox_remote.py"
Cohesion: 0.21
Nodes (11): serve(), remote(), server(), test_a_frame_parquet_cannot_hold_is_reported_not_crashed(), test_a_remote_run_gives_the_same_answer_as_a_local_one(), test_a_wrong_secret_is_rejected_by_the_service(), test_dates_and_text_survive_the_trip_as_parquet(), test_the_service_clamps_the_limits_a_caller_asks_for() (+3 more)

### Community 144 - "conversationSync.test.ts"
Cohesion: 0.09
Nodes (3): empty, v1, v2

### Community 147 - "test_answer_streaming.py"
Cohesion: 0.28
Nodes (7): orchestrator(), RecordingAgent, run_stream(), test_an_agent_error_inside_the_graph_is_reported_not_hung(), test_the_json_entry_point_never_streams(), test_the_sse_carries_the_tokens_before_the_verified_final_response(), test_the_stream_is_detached_after_the_request()

### Community 148 - "make_handler"
Cohesion: 0.21
Nodes (7): make_handler(), do_GET(), do_POST(), _reply(), run_request(), sign_request(), test_requests_without_a_valid_signature_get_401_and_garbage_does_not_kill_the_server()

### Community 158 - "ingestion/document_loader.py"
Cohesion: 0.09
Nodes (13): _extract_docx_text(), _extract_pdf(), _extract_pdf_text(), _extract_plain_text(), _extract_pptx_text(), _join_pages(), _line_key(), _languages() (+5 more)

### Community 161 - "run_ingestion"
Cohesion: 0.29
Nodes (3): main(), run_ingestion(), _write_report()

### Community 167 - "setup_root_logger"
Cohesion: 0.22
Nodes (3): JsonFormatter, SessionFilter, setup_root_logger()

## Knowledge Gaps
- **179 isolated node(s):** `extends`, `next/core-web-vitals`, `maxDuration`, `dynamic`, `maxDuration` (+174 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1317 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **58 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RAGAgent` connect `RAGAgent` to `test_rag_agent.py`, `test_kb_context.py`, `typing`, `LLMClient`, `unsupported_numbers`, `core.py`, `KnowledgeStore`, `lifespan`, `TestRAGAgentFallback`, `gateway/main.py`, `test_answer_streaming.py`, `asyncio`, `StreamingLLM`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `SnapshotManager` connect `SnapshotManager` to `test_enterprise_upgrades.py`, `test_upgrades_validation.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `LLMClient` connect `LLMClient` to `run_ingestion`, `typing`, `data_agent/agent.py`, `unwrap_user_input`, `lifespan`, `KnowledgeStore`, `core.py`, `SearchAgent`, `Orchestrator`, `test_tracing.py`, `RAGAgent`, `gateway/main.py`, `asyncio`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `Orchestrator` (e.g. with `lifespan()` and `BaseAgent`) actually correct?**
  _`Orchestrator` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `AgentRegistry` (e.g. with `TestEnterpriseUpgrades` and `lifespan()`) actually correct?**
  _`AgentRegistry` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `LLMClient` (e.g. with `DataAnalystAgent` and `DatabaseAgent`) actually correct?**
  _`LLMClient` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `extends`, `next/core-web-vitals`, `maxDuration` to the rest of the system?**
  _179 weakly-connected nodes found - possible documentation gaps or missing edges._