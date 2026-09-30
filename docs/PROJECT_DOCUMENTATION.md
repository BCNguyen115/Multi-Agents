# 📁 TÀI LIỆU CHI TIẾT DỰ ÁN MULTI-AGENT ENTERPRISE SYSTEM

---

## 1. 📌 Tổng quan dự án (Project Overview)

### 🎯 Mục đích & Bài toán giải quyết
**Multi-Agent Enterprise System** là một hệ thống **Multi-Agent tự trị cấp doanh nghiệp (Production-Grade Enterprise Multi-Agent System)** được thiết kế theo chuẩn kiến trúc Doanh nghiệp 4 Lớp (4-Layer Enterprise Framework). Dự án giải quyết các bài toán tự động hóa nâng cao bao gồm:

1. **Tra cứu tài liệu doanh nghiệp thông minh (Advanced RAG):** Kết hợp các kỹ thuật HyDE (Hypothetical Document Embeddings), Tìm kiếm kết hợp (Hybrid Search: Vector Embeddings + Full-Text Search), và Tái xếp hạng câu phản hồi sử dụng mô hình Cross-Encoder Reranker (`BAAI/bge-reranker-base`) giúp tối ưu 100% ngữ cảnh tài liệu nội bộ.
2. **Phân tích dữ liệu tự trị & Sinh Executive Dashboard (Data Analysis Swarm):** Tiếp nhận file CSV, tự động chạy quy trình khám phá dữ liệu (EDA), làm sạch mã hóa tự động (`csv_sanitizer`), lập bố cục lưới 12 cột (12-column grid layout system), khởi tạo các biểu đồ tương tác (Apache ECharts, Tremor, AG-Grid), và tổng hợp báo cáo kinh doanh 3 phần (*Diễn biến -> Nguyên nhân -> Khuyến nghị*).
3. **Tìm kiếm Web thời gian thực (Real-time Web Search):** Tích hợp dịch vụ Tavily Search API cùng trình cào dữ liệu web bất đồng bộ Crawl4AI để tổng hợp thông tin, tin tức và báo cáo mới nhất từ Internet có đính kèm trích dẫn nguồn chuẩn.
4. **Truy vấn cơ sở dữ liệu tự động (Database Agent via MCP):** Tự động chuyển đổi câu hỏi tự nhiên thành câu lệnh SQL SELECT an toàn (Read-Only) để thực thi trên PostgreSQL thông qua giao thức Model Context Protocol (MCP) và kiểm tra an toàn câu lệnh với `sqlglot`.
5. **Tích hợp API dịch vụ ngoài (Integration Agent via MCP):** Phân tích ngữ cảnh và tự động sinh HTTP Requests (GET/POST/PUT/DELETE) để giao tiếp với hệ thống bên ngoài qua MCP Client.
6. **Vòng lặp tự sửa lỗi PEV (Plan - Execute - Verify Loop):** Kiểm duyệt chất lượng phản hồi bằng máy trạng thái **LangGraph StateGraph**, tự động kiểm tra trung thực dữ liệu (Zero-Hallucination Audit) và thực thi lại khi kết quả chưa đạt yêu cầu.
7. **Bảo mật & Kiểm định 5 Chuẩn Enterprise (Enterprise Guardrails & Evaluation):** Tự động chặn Prompt Injection / Jailbreak tại Gateway mức `HTTP 400`, che chắn dữ liệu nhạy cảm (PII Redaction), xác thực JWT nội bộ (`jti`, `nbf`), cổng kiểm định Agent Registry Validation Gate (>80% overlap rejection), quản lý Prompt Snapshots (`v1.0.0`) kèm tự động Rollback khi chất lượng sụt giảm >15%, và chạy đánh giá tự động CI/CD Offline Evaluation Pipeline (LLM-as-a-Judge).

---

### 🛠️ Công nghệ sử dụng (Tech Stack)

| Phân loại | Công nghệ / Thư viện chính | Mô tả chức năng |
| :--- | :--- | :--- |
| **Giao diện chính (Primary UI)** | `Next.js 14.2.3` (App Router), `React 18`, `TypeScript`, `TailwindCSS`, `Tremor`, `Apache ECharts`, `AG-Grid React`, `DuckDB WASM` | Web UI hiện đại tại `./frontend` (cổng `3001`). Hiển thị luồng suy nghĩ Agent (PEV Stepper), kéo-thả CSV, render Dashboard 12-column grid và thực thi SQL in-browser. |
| **Giao diện phụ (Secondary UI)** | `Streamlit >=1.36.0`, `AgGrid`, `Plotly` | Giao diện Python phụ tại `src/ui/app.py` (cổng `8501`) phục vụ kiểm thử nhanh backend. |
| **API Gateway & Security** | `FastAPI >=0.111.0`, `Uvicorn`, `sse-starlette`, `Pydantic v2` | Tiếp nhận HTTP/SSE Requests, kiểm duyệt Prompt Injection / Jailbreak early-reject (`security.py`), quản lý connection pool (PostgreSQL, Redis), tắt telemetry PostHog (`telemetry.py`) và nạp bộ nhớ ngắn hạn. |
| **Orchestrator Machine** | `LangGraph >=0.1.5`, `LangChain Core >=0.2.0`, `LangChain Community >=0.2.0` | Điều phối vòng lặp PEV tự trị (`Planner Node` -> `Executor Node` -> `Verifier Node`) với checkpointer `MemorySaver`. |
| **LLM Routing & Proxy** | `LiteLLM >=1.40.0`, `OpenRouter API` (`openai/gpt-4o-mini`) | Unified LLM Gateway hỗ trợ định tuyến, tự động xử lý failover, retry và quản lý API keys. |
| **Agent Registry Gate** | `AgentRegistry` (`src/registry/manager.py`) | Cổng kiểm định tự động cho Agent: tính Cosine Similarity kiểm tra trùng lặp mô tả (>80% rejection) và chạy API probe test bất đồng bộ (`asyncio.wait_for` timeout 3.0s). |
| **Prompt Snapshot & Rollback** | `SnapshotManager` (`src/shared/snapshot_manager.py`) | Quản lý phiên bản Semantic Versioning (`v1.0.0`), lưu snapshot tĩnh safe-state (thread-safe `threading.Lock`), và tự động rollback atomic khi Quality Score giảm >15%. |
| **Authentication & PII Redaction** | `security.py`, `memory_manager.py` (Mem0ai) | Mã hóa ký số JWT internal HMAC-SHA256 (`jti`, `nbf`, `exp`), tự động che chắn dữ liệu nhạy cảm PII (Email, SĐT Việt Nam, CCCD 12 số, Thẻ ngân hàng) trước khi ghi bộ nhớ dài hạn. |
| **CSDL Vector & Metadata** | `PostgreSQL 16`, `pgvector`, `SQLAlchemy`, `asyncpg` | Lưu trữ dữ liệu hệ thống, bảng nhúng vector `rag_chunks` (1536 chiều) và bảng `knowledge_documents`. |
| **Cache & Short-term Memory** | `Redis 5.0+`, `redis-py (async)` | Bộ nhớ đệm hội thoại theo phiên (sliding window history 5 lượt chat) và quản lý file CSV active. DB 0 cho Session/Cache, DB 1 cho Langfuse. |
| **Long-term Memory** | `Mem0ai >=0.1.0`, `MemoryManager` | Quản lý bộ nhớ dài hạn, lưu vết ngữ cảnh và sở thích người dùng qua từng phiên làm việc; lọc cảnh báo `UserWarning` của Qdrant local. |
| **Reranker Service** | `HuggingFace TEI (Text Embeddings Inference)`, `BAAI/bge-reranker-base` | Service container độc lập (`agent_reranker`, cổng `8080`) thực thi tinh lọc kết quả tìm kiếm nâng cao từ Top 20 xuống Top 5. |
| **Search & Scraping Engine** | `Tavily Search API`, `Crawl4AI >=0.4.0` | Tìm kiếm dữ liệu web thời gian thực và cào trích xuất nội dung Markdown bất đồng bộ. |
| **Tool Execution Protocol** | `Model Context Protocol (MCP)` via `MCPClient` | Giao thức chuẩn hóa thực thi công cụ bên ngoài cho `DatabaseAgent` và `IntegrationAgent`. |
| **Observability & Tracing** | `Langfuse V2 SDK` (`langfuse[langchain]>=2.36.0,<3.0.0`) | Giám sát tự host theo dõi Latency, Token Usage, Cost và Trace tree; hỗ trợ fallback import `CallbackHandler` đa phiên bản. |
| **Data Quality & Guardrails** | `sqlglot>=25.0.0`, `chardet>=5.0.0` | Tự động phát hiện bảng mã CSV, làm sạch tiêu đề và kiểm tra an toàn câu lệnh SQL. |
| **Offline Evaluation & Testing** | `run_offline_eval.py`, `Pytest` | Pipeline đánh giá chất lượng tự động LLM-as-a-Judge trên Golden Dataset (`quality_gate_threshold >= 0.85`) và bộ 53 unit tests (`test_enterprise_upgrades.py`). |

---

## 2. 🌲 Cấu trúc thư mục & Tệp tin chi tiết (Directory Structure)

```
multi_agent_mvp/
├── .env                                  # [File] Khai báo biến môi trường hệ thống chính
├── .env.example                          # [File] Mẫu biến môi trường chuẩn bao gồm HF_TOKEN & INTERNAL_JWT_SECRET
├── AGENT_PROMPTS.md                      # [File] Tổng hợp System Prompts cho các Agent & Orchestrator (Version v1.0.0)
├── Dockerfile                            # [File] Dockerfile build image cho FastAPI Gateway Backend
├── SYSTEM_ARCHITECTURE.md                # [File] Tài liệu mô tả chi tiết kiến trúc hệ thống 4 lớp
├── PROJECT_DOCUMENTATION.md              # [File] Tài liệu chi tiết toàn bộ dự án
├── docker-compose.yml                    # [File] File orchestration khởi chạy 7 Docker services
├── eval_report.json                      # [File] Báo cáo chi tiết kết quả đánh giá chất lượng hệ thống (JSON)
├── eval_report.md                        # [File] Báo cáo tổng hợp KPI đánh giá chất lượng hệ thống (Markdown)
├── requirements.txt                      # [File] Khai báo các thư viện Python phụ thuộc Backend (langfuse[langchain], mem0ai)
├── run_ingestion.py                      # [File] Script ETL cắt khúc, nhúng vector và nạp tài liệu vào pgvector
├── dataset/                              # [Folder] Thư mục chứa tập tài liệu mẫu và Golden Dataset
│   ├── golden_eval_dataset.json          # [File] Tập dữ liệu 10 kịch bản test chuẩn cho Offline Evaluation Pipeline
│   ├── corporate/                        # [Folder] Dữ liệu mẫu quy trình doanh nghiệp
│   ├── msa/                              # [Folder] Dữ liệu mẫu hợp đồng khung dịch vụ MSA
│   ├── nda/                              # [Folder] Dữ liệu mẫu thỏa thuận bảo mật NDA
│   ├── purchase/                         # [Folder] Dữ liệu mẫu hợp đồng mua bán
│   ├── sow/                              # [Folder] Dữ liệu mẫu phụ lục phạm vi công việc SOW
│   └── test_data/                        # [Folder] Dữ liệu CSV mẫu kiểm thử Data Agent
├── model_cache/                          # [Folder] Thư mục lưu cache các mô hình HuggingFace / SentenceTransformers
├── rag_pipeline/                         # [Folder] Sub-pipeline RAG chạy độc lập
│   ├── main.py                           # [File] CLI runner cho quy trình RAG độc lập
│   ├── requirements.txt                  # [File] Thư viện phụ thuộc riêng cho RAG pipeline
│   └── src/                              # [Folder] Các module loader, chunker, embedder, retriever phụ trợ RAG
├── scratch/                              # [Folder] Kịch bản kiểm thử & xác minh refactor hệ thống
│   ├── test_backend_comprehensive.py     # [File] Integration test cho toàn bộ API Gateway
│   ├── test_data_agent_refactor.py       # [File] Test kiểm tra Data Analyst Agent Swarm
│   ├── test_refactor_verification.py     # [File] Test xác minh các module sau refactor
│   ├── test_reflection_loop_verification.py # [File] Test vòng lặp tự phản hồi PEV Loop
│   ├── test_summary_metrics_fix.py       # [File] Test xác minh logic tính toán KPI metrics
│   └── test_upgrades_validation.py       # [File] Test tổng thể nâng cấp hệ thống
├── scripts/                              # [Folder] Kịch bản kiểm thử tự động CI/CD
│   └── run_offline_eval.py               # [File] Runner đánh giá chất lượng LLM-as-a-Judge (Dual-mode: offline/live, Gate >= 0.85)
├── tests/                                # [Folder] Bộ kiểm thử Unit & Integration Test backend (Pytest)
│   └── test_enterprise_upgrades.py       # [File] 53 Unit tests kiểm thử toàn bộ 5 module Enterprise Upgrades
├── src/                                  # [Folder] Mã nguồn chính Backend Gateway & Orchestrator
│   ├── config.py                         # [File] Pydantic Settings đọc cấu hình môi trường (.env, HF_TOKEN, JWT Secret)
│   ├── __init__.py                       # [File] Module initializer
│   ├── agents/                           # [Folder] Các Agent chuyên biệt kế thừa từ BaseAgent
│   │   ├── base_agent.py                 # [File] Abstract Base Class chuẩn hóa interface Agent
│   │   ├── data_agent/                   # [Folder] Data Analyst Agent Swarm (EDA, Dashboard, Storyteller)
│   │   │   └── agent.py                  # [File] Logic 5 Sub-Agents xử lý phân tích CSV & sinh Dashboard Spec
│   │   ├── db_agent/                     # [Folder] Database Agent (Sinh SQL SELECT via MCP)
│   │   │   └── agent.py                  # [File] Logic chuyển ngữ sang SQL & thực thi
│   │   ├── integration_agent/            # [Folder] Integration Agent (Gọi REST API via MCP)
│   │   │   └── agent.py                  # [File] Logic sinh HTTP Request & gọi API ngoài
│   │   ├── rag_agent/                    # [Folder] RAG Agent (Tra cứu tài liệu nội bộ)
│   │   │   ├── agent.py                  # [File] Logic RAG kết hợp HyDE, Hybrid Search & TEI Reranker
│   │   │   └── knowledge.py              # [File] KnowledgeStore thao tác với pgvector table
│   │   └── search_agent/                 # [Folder] Web Search Agent thời gian thực
│   │       └── agent.py                  # [File] Logic gọi Tavily Search API & Crawl4AI scraper
│   ├── api/                              # [Folder] Module định tuyến API legacy
│   │   └── gateway.py                    # [File] Router API phụ
│   ├── gateway/                          # [Folder] API Gateway chính của hệ thống
│   │   └── main.py                       # [File] FastAPI application (/api/chat, /api/chat/stream, /api/analyze, Early Prompt Injection Block)
│   ├── ingestion/                        # [Folder] Pipeline nạp và xử lý tài liệu văn bản
│   │   ├── chunker.py                    # [File] Cắt nhỏ tài liệu theo Section với Recursive Splitter
│   │   ├── document_loader.py            # [File] Trích xuất văn bản từ PDF, DOCX, TXT với chardet
│   │   └── embedder.py                   # [File] Tạo Vector Embedding (OpenAI / Local)
│   ├── orchestrator/                     # [Folder] Bộ điều phối tự trị LangGraph (PEV Loop Engine)
│   │   ├── core.py                       # [File] StateGraph quy trình Planner -> Executor -> Verifier
│   │   ├── prompt_templates.py           # [File] Mẫu prompt hệ thống cho Planner & Verifier (v1.0.0)
│   │   ├── state.py                      # [File] Định nghĩa TypedDict AgentState schema
│   │   └── verifier.py                   # [File] Strict Schema Audit Verifier (Zero-Hallucination)
│   ├── registry/                         # [Folder] Quản lý Đăng ký và Tra cứu Agent
│   │   └── manager.py                    # [File] AgentRegistry với Validation Gate (Cosine >80% overlap rejection & async probe)
│   ├── shared/                           # [Folder] Các dịch vụ hạ tầng & dùng chung (Layer 2 & 3)
│   │   ├── csv_sanitizer.py              # [File] Tự động phát hiện bảng mã (chardet) & làm sạch tiêu đề CSV
│   │   ├── llm_client.py                 # [File] LiteLLM Proxy Wrapper tích hợp Langfuse Tracing & CallbackHandler fallback
│   │   ├── logger.py                     # [File] Custom JSON Structured Logger
│   │   ├── mcp_client.py                 # [File] Model Context Protocol Client (SQL & REST execution)
│   │   ├── memory_manager.py             # [File] Mem0 Long-term Memory Manager tích hợp PII Redaction (CCCD, SĐT, Email, Card)
│   │   ├── postgres_client.py            # [File] Asyncpg PostgreSQL Connection Pool Client
│   │   ├── redis_client.py               # [File] Async Redis Client (Session history sliding window 5 turns)
│   │   ├── reranker_client.py            # [File] Client gọi TEI Cross-Encoder Reranker service
│   │   ├── security.py                   # [File] Internal JWT Auth (HMAC-SHA256, jti, nbf) & Heuristic Prompt Injection Scanner (NFKC + Base64)
│   │   ├── snapshot_manager.py           # [File] Quản lý Prompt Snapshots v1.0.0 & Tự động CI/CD Atomic Rollback (thread-safe)
│   │   └── telemetry.py                  # [File] Singleton Telemetry Controller (Tắt PostHog & triệt tiêu cảnh báo HF Hub)
│   └── ui/                               # [Folder] Giao diện Streamlit cũ (Legacy UI)
│       └── app.py                        # [File] Giao diện Streamlit Python (Port 8501)
└── frontend/                             # [Folder] Giao diện người dùng Next.js 14 (Layer 1 Frontend)
    ├── Dockerfile                        # [File] Dockerfile build ứng dụng Next.js sản xuất
    ├── UI_ANIMATION_AUDIT.md             # [File] Tài liệu kiểm thử và tối ưu hiệu ứng UI/UX
    ├── package.json                      # [File] Khai báo dependencies npm (Next.js, Tremor, ECharts, AG-Grid, DuckDB)
    ├── next.config.mjs                   # [File] Cấu hình Next.js (WASM support, headers)
    ├── tailwind.config.js                # [File] Cấu hình TailwindCSS theme & plugins
    ├── tsconfig.json                     # [File] Cấu hình TypeScript compiler options
    ├── app/                              # [Folder] Next.js App Router Pages
    │   ├── globals.css                   # [File] Dark mode theme tokens, custom scrollbars, keyframe animations
    │   ├── layout.tsx                    # [File] Root Layout đính kèm font Inter và metadata SEO
    │   ├── page.tsx                      # [File] Trang chủ chính kết nối Sidebar, Header, Chat, Dashboard & Search
    │   └── api/analyze/route.ts          # [File] Route Handler proxy upload CSV sang FastAPI Gateway
    ├── components/                       # [Folder] Danh sách các UI React Components
    │   ├── AgentSelectorInChat.tsx       # [File] Dropdown chọn chế độ Agent thủ công trong Chat
    │   ├── AgentThoughtStepper.tsx       # [File] Component hiển thị chi tiết tiến trình suy nghĩ của Agent
    │   ├── ChatInput.tsx                 # [File] Khung nhập câu hỏi, phím tắt Enter/Shift+Enter & đính kèm CSV
    │   ├── ChatInterface.tsx             # [File] Khung giao diện trò chuyện chính, tự động cuộn & quản lý SSE listener
    │   ├── ChatMessage.tsx               # [File] Bong bóng tin nhắn với Markdown syntax, nút copy mã & trích dẫn RAG
    │   ├── CSVUploader.tsx               # [File] Component kéo-thả file CSV (giới hạn 10MB)
    │   ├── DataSummaryView.tsx           # [File] Bảng tóm tắt dữ liệu & chạy truy vấn SQL DuckDB WASM in-browser
    │   ├── EnterpriseDashboard.tsx       # [File] Khung hiển thị Executive Dashboard chính kèm chuyển tab
    │   ├── Header.tsx                    # [File] Thanh header trên cùng kèm nút chuyển giao diện sáng/tối
    │   ├── PEVStepper.tsx                # [File] Thanh hiển thị 3 bước PEV (Plan -> Execute -> Verify) real-time từ SSE
    │   ├── SearchView.tsx                # [File] Khung kết quả tìm kiếm Web thời gian thực đính kèm trích dẫn Tavily/Crawl4AI
    │   ├── Sidebar.tsx                   # [File] Thanh điều hướng bên trái (Lịch sử hội thoại LocalStorage, lọc & tạo hội thoại mới)
    │   ├── SourcesList.tsx               # [File] Drawer hiển thị danh sách trích dẫn nguồn RAG kèm điểm cosine similarity
    │   ├── ui/                           # [Folder] UI primitives
    │   │   └── FptLogo.tsx               # [File] Logo doanh nghiệp (SVG Component)
    │   └── dashboard/                    # [Folder] Thành phần hiển thị Executive Dashboard
    │       ├── DashboardSkeleton.tsx     # [File] Hiệu ứng skeleton loading khi đang phân tích
    │       ├── DynamicDashboard.tsx      # [File] Bố cục lưới 12 cột, KPI Cards, ECharts widgets & AG-Grid table
    │       └── EChartComponent.tsx       # [File] Wrapper linh hoạt cho Apache ECharts hỗ trợ resize & theme
    ├── lib/                              # [Folder] Thư viện tiện ích và xử lý dữ liệu Frontend
    │   ├── duckdb.ts                     # [File] Engine khởi tạo và chạy DuckDB WASM ở Browser
    │   ├── sse.ts                        # [File] Client quản lý Server-Sent Events kết nối /api/chat/stream
    │   ├── storage.ts                    # [File] Quản lý lưu trữ phiên hội thoại & DashboardSpec trong LocalStorage
    │   └── types.ts                      # [File] Khai báo các TypeScript Interfaces (DashboardSpec, ChatMessage, v.v.)
    ├── public/                           # [Folder] Tài nguyên tĩnh (Logo FPT, PDF demo)
    └── tests/                            # [Folder] Bộ kiểm thử tự động Playwright E2E
        ├── playwright.config.ts          # [File] Cấu hình Playwright test runner
        ├── fixtures/                     # [Folder] File CSV dữ liệu mẫu cho E2E test (`sample_sales.csv`)
        ├── pages/                        # [Folder] Page Object Models (`ChatPage.ts`, `DashboardPage.ts`, `SidebarPage.ts`)
        └── specs/                        # [Folder] 5 Kịch bản test E2E (Sidebar, SSE Stream, Upload CSV, Dynamic Dashboard, Cross-Filtering)
```

---

## 3. 📄 Phân tích chi tiết chức năng từng File & Module

| Đường dẫn File / Thư mục | Chức năng & Trách nhiệm chính trong hệ thống |
| :--- | :--- |
| **`src/`** | **Thư mục chứa toàn bộ mã nguồn chính của Backend (Gateway, Orchestrator, Agents, Shared Services).** |
| `src/gateway/main.py` | FastAPI App chính. Khởi tạo lifespan kết nối PostgreSQL, Redis; xuất `HF_TOKEN`, gọi `disable_telemetry()` triệt tiêu cảnh báo; tích hợp bảo vệ Prompt Injection early-reject (`HTTP 400 Bad Request`) tại `/api/chat`, `/api/chat/stream`, `/api/analyze`. |
| `src/orchestrator/core.py` | Trái tim điều phối tự trị sử dụng **LangGraph StateGraph**. Quản lý quy trình PEV Loop (`_planner_node` -> `_executor_node` -> `_verifier_node`) và phát SSE stream. |
| `src/orchestrator/state.py` | Định nghĩa schema trạng thái `AgentState` (TypedDict) truyền qua các node trong StateGraph (`query`, `session_id`, `plan`, `target_agent`, `execution_result`, `is_verified`, `verifier_feedback`, `retry_count`, `history`, `long_term_memories`, `pev_trace`). |
| `src/orchestrator/verifier.py` | Strict Schema Audit Verifier (`Zero-Hallucination Audit`). Đối soát 100% cột trong `DashboardSpec` với tiêu đề dữ liệu CSV thực tế để loại bỏ hoàn toàn suy đoán ảo. |
| `src/orchestrator/prompt_templates.py` | Lưu trữ mẫu prompt chuẩn hóa cho Planner Node và Verifier Node. Khai báo hằng số phiên bản `PROMPT_VERSION = "v1.0.0"`. |
| `src/agents/base_agent.py` | Abstract Base Class quy định hợp đồng bắt buộc cho mọi Agent (`process_request`, `get_metadata`). |
| `src/agents/data_agent/agent.py` | **Data Analyst Agent Swarm.** Gồm 5 sub-agents (Analytics Executor, Layout Architect, Chart Spec Builder, Storyteller, Quality Audit Verifier) xử lý EDA và sinh Executive Dashboard JSON chuẩn 12 cột. |
| `src/agents/db_agent/agent.py` | Database Agent. Dùng LLM chuyển câu hỏi tự nhiên thành SQL SELECT hợp lệ (Read-Only) và gửi qua MCP Client để thực thi trên PostgreSQL. |
| `src/agents/integration_agent/agent.py` | Integration Agent. Phân tích yêu cầu tích hợp API ngoài, tự động sinh thông số HTTP Request (GET/POST/PUT/DELETE) và gọi qua MCP Client. |
| `src/agents/rag_agent/agent.py` | RAG Agent. Thực hiện tìm kiếm tri thức nâng cao (HyDE + Hybrid Search + TEI Cross-Encoder Reranker) và tổng hợp câu trả lời dựa trên ngữ cảnh. |
| `src/agents/rag_agent/knowledge.py` | Quản lý bảng nhúng `rag_chunks` trên PostgreSQL pgvector, thực hiện câu truy vấn Cosine Similarity + Full-Text Search (`tsvector`). |
| `src/agents/search_agent/agent.py` | Search Agent. Gọi Tavily Search API để tìm thông tin web và dùng Crawl4AI cào trích xuất dữ liệu Markdown chi tiết. |
| `src/registry/manager.py` | **AgentRegistry với Validation Gate.** Quản lý danh sách Agent; tự động tính Cosine Similarity từ mô tả (`description`) để từ chối đăng ký nếu trùng lặp >80%; thực thi API probe test bất đồng bộ (`asyncio.wait_for` timeout 3s). Hỗ trợ cả `register()` sync và `register_async()`. |
| `src/shared/security.py` | **Internal Security & Prompt Injection Scanner.** Phát hành token JWT internal HMAC-SHA256 đính kèm claims `jti`, `nbf`, `exp`, `iss`, `sub`; kiểm tra an toàn câu hỏi với normalization layer (NFKC, xóa zero-width) và quét giải mã Base64 payload. |
| `src/shared/snapshot_manager.py` | **SnapshotManager & CI/CD Rollback.** Lưu trữ snapshot tĩnh của Agent (thread-safe `threading.Lock`, semver `v1.0.0`, UUID snapshot ID) và tự động thực hiện Rollback atomic (loại bỏ snapshot lỗi khỏi lịch sử) khi chất lượng sụt giảm >15%. |
| `src/shared/telemetry.py` | **Singleton Telemetry Controller.** Tắt toàn bộ PostHog telemetry, LiteLLM telemetry, mem0 telemetry và thêm bộ lọc triệt tiêu cảnh báo unauthenticated requests của HuggingFace Hub. |
| `src/shared/memory_manager.py` | **MemoryManager (Mem0ai).** Quản lý bộ nhớ dài hạn; tích hợp PII Redaction Pipeline (`redact_pii`) tự động mã hóa Email, Số điện thoại Việt Nam (0xxx/+84xxx), CCCD (12 chữ số) và Thẻ ngân hàng trước khi lưu trữ. |
| `src/shared/csv_sanitizer.py` | Module làm sạch dữ liệu CSV: tự động phát hiện mã hóa ký tự (`chardet`), loại bỏ byte order mark (BOM), dọn dẹp dòng trống và tiêu đề cột (`sanitize_column_names`). |
| `src/shared/llm_client.py` | **Unified LLM Client.** Wrapper LiteLLM quản lý gọi mô hình qua OpenRouter và tự động ghi log telemetry tới Langfuse V2. Chuỗi import `CallbackHandler` linh hoạt 4 cấp. |
| `src/shared/postgres_client.py` | Client asyncpg quản lý connection pool và thực thi truy vấn tới PostgreSQL Database. |
| `src/shared/redis_client.py` | Client Redis async quản lý sliding window conversation history (5 lượt chat), lưu file CSV active và hỗ trợ pub/sub. |
| `src/shared/reranker_client.py` | Client tương tác với dịch vụ TEI Reranker container (`BAAI/bge-reranker-base`) để xếp hạng lại tài liệu từ Top 20 xuống Top 5. |
| `src/shared/mcp_client.py` | Client giao thức Model Context Protocol (MCP) dùng để thực thi câu lệnh SQL và HTTP REST Requests an toàn. |
| `src/shared/logger.py` | Custom Structured Logger ghi log dạng JSON chuẩn hóa theo phiên `session_id`. |
| `src/config.py` | Quản lý biến cấu hình ứng dụng bằng Pydantic `BaseSettings` (bao gồm `INTERNAL_JWT_SECRET` và `HF_TOKEN`). |
| `scripts/run_offline_eval.py` | **Offline Evaluation Pipeline Runner.** Chạy đánh giá chất lượng tự động LLM-as-a-Judge trên tập dữ liệu Golden Dataset (`dataset/golden_eval_dataset.json`). Hỗ trợ chế độ `--mode=offline` và `--mode=live` với `asyncio.Semaphore` giới hạn concurrency, xuất báo cáo JSON/Markdown và kiểm tra Quality Gate (`>= 0.85`). |
| `tests/test_enterprise_upgrades.py` | **Pytest Enterprise Test Suite.** 53 unit & integration tests kiểm thử toàn bộ 5 module nâng cấp (Validation Gate, Snapshot Rollback, JWT Auth, PII Redaction, Prompt Injection Scanner). |
| `run_ingestion.py` | Script nạp dữ liệu độc lập chạy quy trình đọc file trong `dataset/`, tạo vector nhúng và đẩy vào pgvector. |
| **`frontend/`** | **Thư mục ứng dụng Web UI sản xuất xây dựng trên Next.js 14 App Router.** |
| `frontend/app/page.tsx` | Trang chính của giao diện, tích hợp Sidebar, Header, ChatInterface, EnterpriseDashboard và SearchView. |
| `frontend/app/api/analyze/route.ts` | Next.js API Route proxy tiếp nhận file CSV từ người dùng và gửi sang FastAPI `/api/analyze`. |
| `frontend/components/ChatInterface.tsx` | Hộp thoại Chat hiển thị tin nhắn, trích dẫn nguồn RAG, và tiến trình suy nghĩ của các Agent. |
| `frontend/components/PEVStepper.tsx` | Component trực quan hóa 3 bước PEV (Planner -> Executor -> Verifier) thời gian thực từ luồng SSE. |
| `frontend/components/DataSummaryView.tsx` | Khung hiển thị bảng dữ liệu & truy vấn SQL trực tiếp bằng DuckDB WASM ở Browser. |
| `frontend/components/dashboard/DynamicDashboard.tsx` | Executive Dashboard hiển thị lưới 12 cột linh hoạt (KPI Cards, ECharts Widgets, AG-Grid Data Table). |
| `frontend/lib/duckdb.ts` | Tích hợp DuckDB WASM giúp người dùng thực hiện câu lệnh SQL trực tiếp trên file CSV ngay tại Browser mà không cần gọi server. |
| `frontend/lib/sse.ts` | Quản lý kết nối EventSource nhận stream sự kiện real-time từ `/api/chat/stream`. |
| `frontend/lib/storage.ts` | Trình quản lý lưu trữ LocalStorage duy trì lịch sử hội thoại và cấu hình `DashboardSpec`. |
| `frontend/tests/` | Bộ kiểm thử Playwright E2E kiểm tra toàn bộ luồng hoạt động UI trên 5 file kịch bản test. |
| **`docker-compose.yml`** | File cấu hình Docker Compose khởi chạy 7 container services đồng bộ (`postgres`, `redis`, `backend`, `frontend`, `langfuse-web`, `langfuse-worker`, `tei-reranker`). |
| **`requirements.txt`** | Danh sách thư viện Python cho Backend (`langfuse[langchain]>=2.36.0,<3.0.0`, `langchain-community>=0.2.0`, `langgraph`, `litellm`, `mem0ai`, `asyncpg`, `pandas`,...). |
| **`AGENT_PROMPTS.md`** | Tập hợp toàn bộ System Prompts chuẩn hóa được sử dụng bởi Orchestrator và các Agents (Semantic Version `v1.0.0`). |

---

## 4. 🛡️ 5 Hạng mục Nâng cấp Kiến trúc Enterprise & Guardrails

Hệ thống tích hợp 5 hạng mục bảo vệ & kiểm định tự động theo tiêu chuẩn Doanh nghiệp:

```
┌─────────────────────────────────────────────────────────────────────────┐
5 CHUẨN ENTERPRISE GUARDRAILS & EVALUATION PIPELINE
├─────────────────────────────────────────────────────────────────────────┤
│ 1. Agent Registry Validation Gate (src/registry/manager.py)             │
│    - Cosine Similarity Bag-of-words > 80% overlap rejection             │
│    - Async API Probe Test (asyncio.wait_for timeout 3.0s)              │
├─────────────────────────────────────────────────────────────────────────┤
│ 2. Agent Versioning & Snapshot Manager (src/shared/snapshot_manager.py)  │
│    - Semantic Versioning (v1.0.0) cho Prompt Templates & Metadata       │
│    - Thread-safe (threading.Lock), UUID Snapshot IDs, Atomic JSON persistence│
│    - Automated Atomic Rollback (loại bỏ snapshot lỗi) khi Quality drop >15%│
├─────────────────────────────────────────────────────────────────────────┤
│ 3. Internal JWT Mutual Authentication & PII Redaction                    │
│    - HMAC-SHA256 JWT Token signing (claims: jti, nbf, exp, iss, sub)   │
│    - PII Redaction Pipeline (Email, SĐT VN 0x/84x, CCCD 12 số, Card)   │
├─────────────────────────────────────────────────────────────────────────┤
│ 4. Dedicated Gateway Prompt Injection Defense (src/shared/security.py)  │
│    - Early-Reject tại Gateway (/api/chat, /api/chat/stream, /api/analyze)│
│    - Normalization Layer (Unicode NFKC + Zero-width stripping)          │
│    - Detection Engine (Direct Overrides, DAN mode, Leakage, Base64 Payload)│
├─────────────────────────────────────────────────────────────────────────┤
│ 5. Continuous Offline Evaluation Pipeline (scripts/run_offline_eval.py) │
│    - Golden Dataset (dataset/golden_eval_dataset.json - 10 test cases)   │
│    - Tool Call Accuracy, RAG Faithfulness, Hallucination Rate           │
│    - Dual-mode (offline / live), Quality Gate threshold >= 0.85         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 🧱 Kiến trúc hệ thống & Luồng dữ liệu (Architecture & Data Flow)

### 🏛️ Mô hình Kiến trúc Doanh nghiệp 4 Lớp (4-Layer Framework)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: PRESENTATION LAYER (Giao diện người dùng)                      │
│ - Next.js 14 App Router UI (React 18, TailwindCSS, Tremor, ECharts)     │
│ - Live Interactive 12-Col Dashboard, AG-Grid, DuckDB WASM Engine       │
│ - Real-time PEV Stepper Visualizer (SSE Stream Listener)                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │  HTTP / SSE Streaming
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: MEMORY & CONTEXT LAYER (Quản lý Bộ nhớ & Ngữ cảnh)             │
│ - Short-term Memory: Redis DB 0 (Sliding Window History - 5 lượt chat)  │
│ - Long-term Memory: Mem0ai MemoryManager + PII Redaction Pipeline       │
│ - Redis CSV Active State Store (Lưu thông tin dataset phiên hiện tại)   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: AGENT SWARM & TOOLS LAYER (Tầng Điều phối & Agent Tự trị)     │
│ - LangGraph Orchestrator Engine (StateGraph PEV Loop Machine)            │
│   ├── Planner Node    ──► Phân tích yêu cầu, nạp bộ nhớ, lập Kế hoạch   │
│   ├── Executor Node   ──► Chuyển giao tới Agent chuyên biệt thực thi    │
│   └── Verifier Node   ──► Đối soát kết quả & kiểm duyệt chất lượng       │
│ - Agent Registry Validation Gate (>80% overlap rejection & probe)       │
│ - Specialized Agents Swarm:                                             │
│   ├── Data Analyst Swarm (5 Sub-agents: EDA, Layout, Charts, Story)     │
│   ├── RAG Agent (HyDE + Hybrid Vector/FTS Search + TEI Reranker)        │
│   ├── Search Agent (Real-time Tavily + Crawl4AI Markdown Scraper)       │
│   ├── Database Agent (SQL Generator & Executor via MCP Protocol)        │
│   └── Integration Agent (REST Request Builder & Executor via MCP)       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 4: INFRASTRUCTURE & OBSERVABILITY LAYER (Hạ tầng & Giám sát)      │
│ - Security Gateway Guardrails (Prompt Injection Scan, JWT Auth)         │
│ - PostgreSQL 16 + pgvector (`rag_chunks`, `knowledge_documents`)        │
│ - TEI Cross-Encoder Reranker Container (`BAAI/bge-reranker-base`)       │
│ - LiteLLM Router & OpenRouter Proxy (`openai/gpt-4o-mini`)              │
│ - Self-Hosted Langfuse Observability V2 (Web UI & Async Worker Queue)   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 🔄 Luồng dữ liệu chi tiết (Data Flow Steps)

```mermaid
sequenceDiagram
    autonumber
    actor Client as User / Client Browser (Next.js UI)
    participant GW as FastAPI Gateway (/src/gateway/main.py)
    participant Sec as Security Guardrail (src/shared/security.py)
    participant Redis as Redis Cache (DB 0)
    participant Mem as Mem0 MemoryManager (PII Filtered)
    participant Orchestrator as LangGraph PEV Orchestrator
    participant Agent as Specialized Agent (Data/RAG/Search/DB/Integration)
    participant External as External Services (PostgreSQL / TEI / Tavily / MCP)
    participant LF as Langfuse Observability

    Client->>GW: Gửi yêu cầu Chat (`POST /api/chat/stream`) hoặc Upload CSV (`POST /api/analyze`)
    GW->>Sec: 1. Quét Prompt Injection / Jailbreak (`inspect_prompt_safety`)
    alt Phát hiện Injection
        Sec-->>GW: Trả về False + Label vi phạm
        GW-->>Client: Trả về HTTP 400 Bad Request ngay lập tức (Early Reject)
    end

    GW->>LF: 2. Khởi tạo Telemetry Trace Session
    GW->>Redis: Nạp 5 lượt lịch sử chat gần nhất (Short-term Memory)
    Redis-->>GW: Trả về Conversation History
    GW->>Orchestrator: Kích hoạt `astream(initial_state)`

    rect rgb(240, 248, 255)
        note over Orchestrator: 🔁 VÒNG LẶP PEV LOOP (Plan - Execute - Verify)
        
        Orchestrator->>Client: SSE Stream Event: pev_step [planner - active]
        Orchestrator->>Mem: Nạp Long-term Memories liên quan
        Orchestrator->>Orchestrator: 3. Planner Node lập Kế hoạch & Chọn Target Agent
        Orchestrator->>Client: SSE Stream Event: plan {plan, target_agent}
        
        Orchestrator->>Agent: 4. Executor Node chuyển giao công việc cho Agent
        Orchestrator->>Client: SSE Stream Event: pev_step [executor - active]
        
        alt Chế độ RAG Agent
            Agent->>External: Sinh HyDE Hypothetical Doc -> Hybrid Search (pgvector + FTS)
            External-->>Agent: Trả về Top 20 ứng viên
            Agent->>External: Gửi Top 20 qua TEI Reranker (`agent_reranker:8080`)
            External-->>Agent: Trả về Top 5 ngữ cảnh được xếp hạng cao nhất
        else Chế độ Data Analyst Agent
            Agent->>Agent: Chạy 5 Sub-Agents: EDA -> Layout Architect -> Chart Spec -> Storyteller -> Quality Audit
        else Chế độ Search Agent
            Agent->>External: Gọi Tavily Search API & cào nội dung bằng Crawl4AI
        else Chế độ Database / Integration Agent
            Agent->>External: Thực thi SQL hoặc REST Call thông qua MCP Client
        end

        Agent-->>Orchestrator: Trả về `execution_result`
        Orchestrator->>Client: SSE Stream Event: executing {execution_result}
        
        Orchestrator->>Orchestrator: 5. Verifier Node đối soát kết quả với Plan & Schema
        Orchestrator->>Client: SSE Stream Event: verifying {is_verified, verifier_feedback}

        alt Nếu kết quả CHƯA ĐẠT (is_verified = False & retry < 2)
            Orchestrator->>Agent: Lặp lại Executor Node kèm `verifier_feedback`
        end
    end

    Orchestrator->>Client: SSE Stream Event: final_response {response, pev_trace}
    GW->>Redis: Cập nhật Lịch sử câu hỏi & câu trả lời vào Redis
    GW->>Mem: Lưu vết bộ nhớ tương tác mới sau khi áp dụng PII Redaction Pipeline
```

---

## 6. 🔌 Danh sách API & Schema Cấu trúc Dữ liệu

### 🌐 1. Các Endpoints tại API Gateway (`src/gateway/main.py`)

1. **`POST /api/chat/stream`**
   - **Mục đích:** Gửi câu hỏi dạng chat và nhận luồng dữ liệu truyền phát **SSE (Server-Sent Events)** theo từng bước của vòng lặp PEV Loop.
   - **Bảo mật:** Tự động chạy `inspect_prompt_safety()`. Trả về `HTTP 400 Bad Request` nếu phát hiện Prompt Injection.
   - **Request Payload:** `ChatRequest` (`{ "query": str, "session_id": str, "agent_mode": Optional[str] }`).
   - **Events trả về:** `pev_step`, `plan`, `executing`, `verifying`, `final_response`.

2. **`POST /api/chat`**
   - **Mục đích:** Xử lý câu hỏi chat dạng JSON đồng bộ (non-streaming fallback).
   - **Response Payload:** `ChatResponse` (`{ "session_id": str, "response": str, "sources": list[SourceItem], "pev_trace": dict }`).

3. **`POST /api/analyze`**
   - **Mục đích:** Tiếp nhận Upload file CSV (Multipart Form Data), tự động làm sạch mã hóa và khởi tạo cấu hình `Executive Dashboard Spec`.
   - **Request Form:** `file`: UploadFile (CSV), `query`: str, `session_id`: str.
   - **Response Payload:** `AnalyzeResponse` (`{ "session_id": str, "explanation": str, "generated_code": str, "dashboard_spec": dict, "pev_trace": dict }`).

4. **`GET /health`**
   - **Mục đích:** Health-check kiểm tra trạng thái sống của Gateway service (`{"status": "ok"}`).

---

## 7. 🚀 Hướng dẫn cài đặt, Kiểm thử & Vận hành (Setup & Testing)

### 📋 Tiền điều kiện (Prerequisites)
- **Docker** (20.10+) & **Docker Compose** (v2.0+).
- **Python 3.10+** (khi chạy cục bộ không qua Docker).
- **Node.js 18+** & **npm 9+** (khi chạy Frontend cục bộ).
- Khóa API **OpenRouter API Key** và **Tavily API Key**.

---

### 🐳 1. Vận hành bằng Docker Compose

#### **Bước 1: Cấu hình biến môi trường (`.env`)**
```bash
cp .env.example .env
```

Cập nhật các khóa API trong `.env`:
```env
OPENROUTER_API_KEY=sk-or-v1-your-actual-openrouter-key
TAVILY_API_KEY=tvly-your-actual-tavily-key
INTERNAL_JWT_SECRET=your-enterprise-secret-key-change-me
LANGFUSE_ENABLED=true
```

#### **Bước 2: Khởi chạy 7 Docker Services**
```bash
docker-compose up --build -d
```

#### **Bước 3: Thực thi Script Nạp Dữ Liệu RAG (Ingestion)**
```bash
docker exec agent_backend python run_ingestion.py
```

#### **Bước 4: Truy cập ứng dụng**
- 🎨 **Next.js UI:** [http://localhost:3001](http://localhost:3001)
- 🔌 **FastAPI Gateway Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- 📊 **Langfuse Telemetry Dashboard:** [http://localhost:3005](http://localhost:3005)
- 🚀 **TEI Reranker Service Health:** `http://localhost:8080/health`

---

### 🧪 2. Chạy Bộ Kiểm Thử Tự Động (Testing)

#### **Backend Pytest Enterprise Test Suite (53 Tests):**
```bash
python -m pytest tests/test_enterprise_upgrades.py -v
```

#### **Continuous Offline Evaluation Pipeline (LLM-as-a-Judge):**
```bash
python scripts/run_offline_eval.py --mode=offline
```

#### **E2E UI Tests (Playwright):**
```bash
cd frontend
npx playwright test
```

---

### 🔑 3. Danh sách Biến Môi Trường Chính (`.env`)

| Tên biến môi trường | Giá trị mặc định | Mô tả chi tiết |
| :--- | :--- | :--- |
| `OPENROUTER_API_KEY` | `sk-or-v1-...` | Khóa API cấp quyền gọi các mô hình LLM trên OpenRouter. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Base URL chính thức gọi OpenRouter API (`OPENAI_BASE_URL`). |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | Tên mô hình LLM mặc định cho toàn bộ hệ thống. |
| `FAST_LLM_MODEL` | `openai/gpt-4o-mini` | Mô hình LLM tốc độ cao (latency thấp) cho Planner Node & Verifier Node. |
| `HEAVY_LLM_MODEL` | `openai/gpt-4o-mini` | Mô hình LLM chất lượng cao dành cho Data Storyteller & RAG Synthesis. |
| `POSTGRES_URL` | `postgresql://user:password@localhost:5432/multi_agent_db` | Chuỗi kết nối PostgreSQL Database với extension pgvector. |
| `REDIS_URL` | `redis://localhost:6379/0` | Chuỗi kết nối Redis Cache (DB 0 cho Session/Cache). |
| `TAVILY_API_KEY` | `tvly-...` | Khóa API sử dụng dịch vụ tìm kiếm Tavily Web Search. |
| `INTERNAL_JWT_SECRET` | `enterprise-secret...` | Khóa bí mật dùng ký và xác thực token JWT nội bộ giữa các dịch vụ. |
| `HF_TOKEN` | `None` | Token xác thực tùy chọn kết nối tới HuggingFace Hub. |
| `RERANKER_ENDPOINT` | `http://tei-reranker:80/rerank` | Endpoint dịch vụ TEI Cross-Encoder Reranker (`agent_reranker` trong Docker). |
| `RERANK_TOP_K` | `5` | Số lượng tài liệu giữ lại sau bước Rerank (Top 5). |
| `HYBRID_CANDIDATES_K` | `10` | Số lượng ứng viên thô lấy từ bước Hybrid Search trước khi đẩy sang Reranker. |
| `MAX_RERANK_TEXT_LENGTH` | `500` | Giới hạn độ dài văn bản gửi sang TEI Reranker. |
| `RERANKER_TIMEOUT` | `30.0` | Thời gian chờ tối đa (giây) khi gọi TEI Reranker API. |
| `LANGFUSE_ENABLED` | `true` | Bật/tắt tính năng theo dõi telemetry Langfuse. |
| `LANGFUSE_PUBLIC_KEY` | `pk-lf-...` | Public Key truy cập Langfuse Web UI. |
| `LANGFUSE_SECRET_KEY` | `sk-lf-...` | Secret Key dùng gửi telemetry logs đến Langfuse. |
| `LANGFUSE_HOST` | `http://localhost:3005` | Địa chỉ URL dịch vụ Langfuse Web (`http://langfuse-web:3000` trong Docker network). |
| `LOG_LEVEL` | `INFO` | Mức độ chi tiết của Structured JSON Log (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
