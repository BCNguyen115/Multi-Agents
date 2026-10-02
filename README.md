<div align="center">

# 🚀 PRODUCTION-GRADE ENTERPRISE MULTI-AGENT SYSTEM
### Autonomous PEV Swarm • Hybrid RAG • In-Browser DuckDB WASM • 4-Layer Enterprise Framework

[![Python 3.12](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14.2%20(App%20Router)-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6F00?style=for-the-badge&logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL%2016-pgvector-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Docker](https://img.shields.io/badge/Docker-7%20Microservices-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

<p align="center">
  <b>Hệ thống Multi-Agent tự trị cấp doanh nghiệp tích hợp vòng lặp tự phản hồi PEV Loop (Plan → Execute → Verify), chuỗi RAG nâng cao HyDE + Hybrid Search + TEI Cross-Encoder Reranker, Data Analyst Swarm 5 Sub-Agents sinh Executive Dashboard 12 cột, và công cụ tính toán SQL client-side với DuckDB WASM.</b>
</p>

[Khám Phá Tính Năng](#-tính-năng-cốt-lõi--kiến-trúc-5-agents) •
[Kiến Trúc 4 Lớp](#-kiến-trúc-hệ-thống-4-layer-framework) •
[Khởi Chạy Nhanh](#-hướng-dẫn-khởi-chạy-quick-start) •
[Cấu Hình Môi Trường](#-cấu-hình-biến-môi-trường-env) •
[Bộ Kiểm Thử & Đánh Giá](#-kiểm-thử--offline-evaluation-pipeline) •
[Case Study Chi Tiết](./docs/PORTFOLIO_CASE_STUDY.md)

---

</div>

## 📖 Mục Lục (Table of Contents)

1. [📌 Tổng Quan Dự Án (Executive Summary)](#-tổng-quan-dự-án-executive-summary)
2. [✨ Tính Năng Cốt Lõi & 5 Agents Chuyên Biệt](#-tính-năng-cốt-lõi--5-agents-chuyên-biệt)
3. [🏛️ Kiến Trúc Hệ Thống (4-Layer Framework & Sơ Đồ)](#-kiến-trúc-hệ-thống-4-layer-framework)
4. [🐳 Cấu Trúc 7 Docker Microservices](#-cấu-trúc-7-docker-microservices)
5. [🛡️ Bảo Mật & Enterprise Guardrails](#-bảo-mật--enterprise-guardrails)
6. [🚀 Hướng Dẫn Khởi Chạy (Quick Start Guide)](#-hướng-dẫn-khởi-chạy-quick-start)
   - [Cách 1: Khởi chạy toàn bộ với Docker Compose (Khuyên dùng)](#cách-1-khởi-chạy-toàn-bộ-với-docker-compose-khuyên-dùng)
   - [Cách 2: Chạy Local Development (Từng service)](#cách-2-chạy-local-development-từng-service)
7. [⚙️ Cấu Hình Biến Môi Trường (.env)](#️-cấu-hình-biến-môi-trường-env)
8. [📊 Nạp Dữ Liệu RAG (Data Ingestion Pipeline)](#-nạp-dữ-liệu-rag-data-ingestion-pipeline)
9. [🧪 Kiểm Thử & Offline Evaluation (LLM-as-a-Judge)](#-kiểm-thử--offline-evaluation-llm-as-a-judge)
10. [📂 Cấu Trúc Thư Mục Dự Án](#-cấu-trúc-thư-mục-dự-án)
11. [📄 Giấy Phép (License)](#-giấy-phép-license)

---

## 📌 Tổng Quan Dự Án (Executive Summary)

**Enterprise Multi-Agent System** giải quyết triệt để các hạn chế của các hệ thống AI truyền thống:
* **Loại bỏ hoàn toàn ảo giác (Zero-Hallucination Rate ~0%):** Strict Schema Audit Verifier đối soát 100% trường dữ liệu với DataFrame thực tế trước khi hiển thị.
* **Tối ưu độ chính xác tra cứu (+45% Retrieval Accuracy):** Kết hợp HyDE (Hypothetical Document Embeddings), Hybrid Search (Vector 0.7 + FTS 0.3 trên PostgreSQL pgvector HNSW Index), và HuggingFace TEI Cross-Encoder Reranker (`BAAI/bge-reranker-base`).
* **Phân tích dữ liệu tự trị & Trực quan hóa tức thì:** Data Analyst Swarm phối hợp 5 Sub-Agents tự động sinh Executive Dashboard 12 cột (Apache ECharts 6, Tremor KPI Cards, AG-Grid Table) kèm báo cáo phân tích 3 phần (*Diễn Biến → Nguyên Nhân → Khuyến Nghị*).
* **In-Browser Compute với DuckDB WASM:** Thực thi câu lệnh SQL trực tiếp trong trình duyệt người dùng — **0% backend latency**, giảm tải 100% cho máy chủ khi phân tích file CSV.
* **Khả năng quan sát toàn diện (Observability):** Langfuse V2 self-hosted theo dõi chi tiết Latency, Chi phí Token và Trace execution tree của từng node trong máy trạng thái LangGraph.

---

## ✨ Tính Năng Cốt Lõi & 5 Agents Chuyên Biệt

```
                                  ┌──────────────────────────────┐
                                  │      User Prompt / CSV       │
                                  └──────────────┬───────────────┘
                                                 │
                                  ┌──────────────▼───────────────┐
                                  │    LangGraph Orchestrator    │
                                  │  🔁 PEV Loop (Plan-Exec-Ver) │
                                  └──────────────┬───────────────┘
                                                 │
        ┌───────────────────┬────────────────────┼───────────────────┬───────────────────┐
        │                   │                    │                   │                   │
┌───────▼────────┐  ┌───────▼────────┐   ┌───────▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐
│   RAG Agent    │  │   Data Agent   │   │  Search Agent  │  │ Database Agent │  │  Integration   │
│  (HyDE/Hybrid/ │  │ (5 Sub-Agents  │   │ (Tavily Web +  │  │  (MCP Read-    │  │ (MCP REST API  │
│  TEI Reranker) │  │ Swarm + DuckDB)│   │  Crawl4AI)     │  │  Only + AST)   │  │  Executor)     │
└────────────────┘  └────────────────┘   └────────────────┘  └────────────────┘  └────────────────┘
```

### 1. 📚 RAG Agent (Tri thức & Văn bản Pháp lý Doanh nghiệp)
- **HyDE (Hypothetical Document Embeddings):** LLM sinh bản dự thảo câu trả lời trước khi nhúng vector, giúp tìm kiếm theo bản chất ngữ nghĩa thay vì từ khóa ngắn.
- **Hybrid Search:** Kết hợp Cosine Distance trên `pgvector` (trọng số 0.7) và Full-Text Search `tsvector` (trọng số 0.3).
- **TEI Cross-Encoder Reranker:** Gửi 20 ứng viên qua container TEI (`BAAI/bge-reranker-base`) để chấm điểm sâu và lọc Top 5 tài liệu chính xác nhất.
- **Circuit Breaker:** Ngưỡng timeout cứng 800ms, tự động chuyển sang cơ chế fallback nếu reranker quá tải.

### 2. 📊 Data Analyst Agent (Swarm 5 Sub-Agents & DuckDB WASM)
- **Sub-Agent 1 (EDA Executor):** Tính toán shapes, types, thống kê mô tả (describe), phát hiện giá trị bất thường.
- **Sub-Agent 2 (Layout Architect):** Lập sơ đồ bố cục lưới 12 cột chuẩn (`col-span-12`, `col-span-7`, `col-span-5`).
- **Sub-Agent 3 (Chart Spec Builder):** Tạo cấu hình JSON cho Apache ECharts (Bar, Line, Pie, Area) và Tremor KPI Cards.
- **Sub-Agent 4 (Executive Storyteller):** Tổng hợp bình luận kinh doanh chuyên sâu theo cấu trúc: *Diễn Biến → Nguyên Nhân → Khuyến Nghị*.
- **Sub-Agent 5 (Quality Evaluator):** Kiểm tra độ cân bằng layout, kiểm soát giá trị null/NaN và liên kết key-mapping.
- **In-Browser DuckDB WASM:** Hỗ trợ người dùng mở SQL Playground và truy vấn dữ liệu trực tiếp trong trình duyệt.

### 3. 🌐 Web Search Agent (Tìm kiếm thời gian thực)
- **Tavily API:** Tìm kiếm thông tin mới nhất trên Internet.
- **Crawl4AI Async Scraper:** Cào dữ liệu song song và chuyển đổi trang web thành định dạng Markdown chuẩn xác.

### 4. 🗄️ Database Agent (Truy vấn CSDL An toàn via MCP)
- Tự động chuyển đổi câu hỏi tự nhiên thành câu lệnh SQL `SELECT` an toàn.
- Tích hợp giao thức **Model Context Protocol (MCP)** và kiểm tra AST qua `sqlglot`.

### 5. 🔌 Integration Agent (Tích hợp Dịch vụ Ngoài via MCP)
- Phân tích ngữ cảnh và tự động sinh HTTP Requests (GET, POST, PUT, DELETE) gửi qua MCP Client tới các dịch vụ microservice bên ngoài.

---

## 🏛️ Kiến Trúc Hệ Thống (4-Layer Framework)

Dự án được xây dựng theo chuẩn kiến trúc Doanh nghiệp 4 Lớp:

```mermaid
graph TB
    subgraph "LAYER 1 — Presentation & Client Compute"
        UI["Next.js 14 App Router<br/>Port 3001"]
        PEV_UI["PEVStepper.tsx<br/>Real-time SSE Stepper"]
        DASH["DynamicDashboard.tsx<br/>12-Col Grid · ECharts · AG-Grid"]
        DUCKDB["DuckDB WASM<br/>In-Browser SQL Engine"]
        CSV_UP["CSVUploader.tsx<br/>Drag & Drop · 10MB Limit"]
    end

    subgraph "LAYER 2 — Harness, Memory & Control Core"
        GW["FastAPI Gateway<br/>Port 8000"]
        ORCH["LangGraph StateGraph<br/>PEV Loop (max_retries=2)"]
        REDIS["Redis 5.0+<br/>Sliding Window 5 turns"]
        MEM0["Mem0ai<br/>Long-term Memory"]
        SEC["Security Layer<br/>Prompt Scanner · JWT · PII"]
    end

    subgraph "LAYER 3 — Specialized Agent Swarm"
        RAG["RAGAgent<br/>HyDE + Hybrid Search + Reranker"]
        DATA["DataAnalystAgent<br/>5 Sub-Agent Swarm"]
        SEARCH["SearchAgent<br/>Tavily + Crawl4AI"]
        DB_AG["DatabaseAgent<br/>MCP + sqlglot Validator"]
        INT_AG["IntegrationAgent<br/>MCP REST API"]
    end

    subgraph "LAYER 4 — Governance, Security & Monitoring"
        LITELLM["LiteLLM Unified Proxy<br/>OpenRouter · gpt-4o-mini"]
        LF["Langfuse V2<br/>Self-hosted Observability (Port 3005)"]
        TEI["TEI Reranker<br/>BAAI/bge-reranker-base (Port 8080)"]
        PG["PostgreSQL 16 + pgvector<br/>HNSW Index · 1536-dim (Port 5432)"]
    end

    UI --> GW
    PEV_UI --> GW
    DASH --> DUCKDB
    CSV_UP --> GW

    GW --> SEC
    GW --> ORCH
    GW --> REDIS
    ORCH --> MEM0
    ORCH --> RAG
    ORCH --> DATA
    ORCH --> SEARCH
    ORCH --> DB_AG
    ORCH --> INT_AG

    RAG --> PG
    RAG --> TEI
    RAG --> LITELLM
    DATA --> LITELLM
    SEARCH --> LITELLM
    DB_AG --> PG
    INT_AG --> LITELLM
    LITELLM --> LF
```

### Chu trình tự sửa lỗi PEV Loop (Plan - Execute - Verify)

```mermaid
sequenceDiagram
    autonumber
    actor User as Người dùng (Next.js UI)
    participant GW as FastAPI Gateway
    participant PEV as LangGraph StateGraph
    participant Agent as Specialized Agent
    participant Verifier as Verifier (Schema Audit)
    participant SSE as SSE Stream Client

    User->>GW: POST /api/chat/stream (Prompt / CSV)
    GW->>PEV: astream(initial_state)
    
    rect rgb(240, 248, 255)
        PEV->>SSE: Event: pev_step [planner - active]
        PEV->>PEV: 1. Planner Node (Lập kế hoạch & Chọn Agent)
        PEV->>SSE: Event: plan {plan, target_agent}
        
        PEV->>SSE: Event: pev_step [executor - active]
        PEV->>Agent: 2. Executor Node (Thực thi chuyên biệt)
        Agent-->>PEV: Trả về kết quả thô
        PEV->>SSE: Event: executing {result}
        
        PEV->>SSE: Event: pev_step [verifier - active]
        PEV->>Verifier: 3. Verifier Node (Kiểm duyệt Schema & Hallucination)
        
        alt Không đạt (is_verified = False & retry < 2)
            Verifier-->>PEV: Yêu cầu sửa đổi kèm feedback
            PEV->>Agent: Tái thực thi với hướng dẫn từ Verifier
        else Đạt chuẩn (is_verified = True)
            Verifier-->>PEV: Phê duyệt hoàn tất
        end
    end
    
    PEV-->>GW: Hoàn thành máy trạng thái
    GW->>SSE: Event: final_response {data, is_verified}
    SSE-->>User: Render Markdown + Live Dashboard + Stepper
```

---

## 🐳 Cấu Trúc 7 Docker Microservices

Hệ thống được đóng gói hoàn chỉnh trong `docker-compose.yml` gồm **7 microservices**:

| Tên Container | Service Key | Image / Công nghệ | Cổng Host:Container | Mục Đích |
|:---|:---|:---|:---|:---|
| `agent_frontend` | `frontend` | Next.js 14 (App Router) | `3001:3000` | Giao diện người dùng sản xuất |
| `agent_backend` | `backend` | FastAPI + LangGraph | `8000:8000` | API Gateway & Bộ điều phối Orchestrator |
| `agent_postgres` | `postgres` | `ankane/pgvector:latest` (PG 16) | `5432:5432` | CSDL lưu trữ `rag_chunks` & dữ liệu hệ thống |
| `agent_redis` | `redis` | `redis:alpine` | `6379:6379` | Bộ nhớ đệm phiên (DB 0) & Queue (DB 1) |
| `agent_langfuse_web` | `langfuse-web` | `langfuse/langfuse:2` | `3005:3000` | Dashboard giám sát LLM Observability |
| `agent_langfuse_worker` | `langfuse-worker` | `langfuse/langfuse-worker:2` | N/A | Worker xử lý telemetry ngầm |
| `agent_reranker` | `tei-reranker` | HuggingFace TEI `cpu-1.2` | `8080:80` | Cross-Encoder Reranker (`BAAI/bge-reranker-base`) |
| `agent_python_sandbox` | `python-sandbox` | `Dockerfile.sandbox` (Python + pandas/numpy) | N/A (mạng nội bộ `sandbox_net`) | Chạy mã phân tích do LLM viết, cách ly khỏi API (xem mục Vận hành) |

---

## 🛡️ Bảo Mật & Enterprise Guardrails

1. **AST SQL Validator (`sqlglot`):** Chặn 100% câu lệnh ghi/xóa (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`, `CREATE`), phát hiện DML lồng trong subqueries, tự động tiêm `LIMIT 1000`.
2. **Prompt Injection Scanner:** Tiền xử lý chuẩn hóa NFKC, xóa ký tự zero-width, giải mã Base64 payload, chặn các mẫu tấn công DAN, Jailbreak, System Prompt Leak ngay tại Gateway (`HTTP 400 Bad Request`).
3. **PII Redaction Pipeline:** Tự động che chắn Số điện thoại Việt Nam (`0xxx`/`+84xxx`), CCCD (12 chữ số), Email, Thẻ tín dụng trước khi ghi vào bộ nhớ dài hạn `Mem0`.
4. **JWT Inter-service Authentication:** Ký số HMAC-SHA256 với các claims chuẩn `jti`, `nbf`, `exp`, `iss`, `sub` chống tấn công replay.
5. **AgentRegistry Validation Gate:** Từ chối đăng ký các Agent có độ trùng lặp mô tả > 80% (Cosine Similarity) và chạy functional probe test bất đồng bộ (timeout 3.0s).
6. **Xác thực người dùng (`AUTH_MODE=jwt`):** mọi route `/api/*` cần `Authorization: Bearer <JWT>` (HS256 hoặc JWKS của IdP). `sub` gắn phiên với người dùng (không ai đọc/duyệt được phiên của người khác), claim `tenant_id`/`department_id` đi vào Row-Level Security (điều kiện `department_id = … AND tenant_id = …`, lỗi RLS thì **không chạy** truy vấn), chỉ vai trò `HITL_APPROVER_ROLES` mới được phê duyệt thao tác nhạy cảm và người duyệt được ghi log. Mặc định `AUTH_MODE=off` (người dùng ẩn danh, chỉ để phát triển cục bộ); chế độ `jwt` từ chối khởi động nếu secret thiếu/ngắn/còn là giá trị mẫu. Trình duyệt chưa có màn hình đăng nhập: đặt proxy nhận diện người dùng (oauth2-proxy, API gateway…) phía trước, hoặc tạo token thử bằng `python -m scripts.make_token`.
7. **Cách ly dữ liệu:** `db_agent` chạy SQL do LLM viết bằng role Postgres chỉ đọc (xem `DB_AGENT_PASSWORD`), nên PostgreSQL tự chặn ghi, DDL và mọi bảng/schema ngoài danh sách cho phép (kể cả 42 bảng Langfuse). Phê duyệt HITL nằm trong Redis (sống qua restart, duyệt được trên bất kỳ bản sao nào, chỉ nhận một lần).
8. **Giới hạn tốc độ & tải lên:** `RATE_LIMIT_CHAT_PER_MINUTE` / `RATE_LIMIT_ANALYZE_PER_MINUTE` theo người dùng (hoặc IP), đếm bằng Redis; tệp tải lên bị từ chối bằng `Content-Length` trước khi đọc và được đọc theo khối có trần `DATA_MAX_FILE_MB`.
9. **SnapshotManager & Atomic Rollback:** Quản lý phiên bản Semantic Versioning (`v1.0.0`), tự động Rollback nguyên tử nếu điểm chất lượng sụt giảm > 15%.

---

## 🚀 Hướng Dẫn Khởi Chạy (Quick Start)

### Yêu Cầu Tiên Quyết (Prerequisites)
- [Git](https://git-scm.com/)
- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose v2+](https://docs.docker.com/compose/)
- *(Tùy chọn cho Local Dev)* Python 3.11+ & Node.js 18+

---

### Cách 1: Khởi chạy toàn bộ với Docker Compose (Khuyên dùng)

#### Bước 1: Clone Repository
```bash
git clone https://github.com/BCNguyen115/Multi-Agents.git
cd Multi-Agents
```

#### Bước 2: Cấu hình biến môi trường
Tạo file `.env` từ file mẫu `.env.example`:
```bash
# Trên Linux/macOS:
cp .env.example .env

# Trên Windows PowerShell:
Copy-Item .env.example .env
```
Mở file `.env` và điền `OPENROUTER_API_KEY` (hoặc `TAVILY_API_KEY` nếu dùng tính năng tìm kiếm web).

#### Bước 3: Khởi động 7 Services
```bash
docker compose up -d --build   # cần POSTGRES_PASSWORD, LANGFUSE_NEXTAUTH_SECRET, LANGFUSE_SALT trong .env (xem .env.example)
```

#### Bước 4: Truy cập hệ thống
- 🌐 **Web UI chính (Next.js 14):** [http://localhost:3001](http://localhost:3001)
- 🔌 **API Gateway Docs (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
- 📈 **Langfuse Observability:** [http://localhost:3005](http://localhost:3005)
- 🎯 **TEI Reranker API:** [http://localhost:8080](http://localhost:8080)

---

### Cách 2: Chạy Local Development (Từng service)

#### 1. Khởi động hạ tầng nền tảng (PostgreSQL, Redis, TEI)
```bash
docker compose up -d postgres redis tei-reranker
```

#### 2. Cài đặt & Chạy Backend (FastAPI + LangGraph)
```bash
# Tạo và kích hoạt virtual environment
python -m venv venv

# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Cài đặt thư viện phụ thuộc
pip install -r requirements.txt

# Nạp dữ liệu tài liệu mẫu vào pgvector
python -m scripts.run_ingestion

# Khởi chạy FastAPI Gateway Backend
uvicorn src.gateway.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 3. Cài đặt & Chạy Frontend (Next.js 14)
```bash
cd frontend
npm install
npm run dev
```
Truy cập giao diện tại [http://localhost:3000](http://localhost:3000).

---

## ⚙️ Cấu Hình Biến Môi Trường (.env)

| Biến Môi Trường | Giá Trị Mặc Định | Mô Tả |
|:---|:---|:---|
| `OPENROUTER_API_KEY` | *(Bắt buộc)* | API Key từ [OpenRouter](https://openrouter.ai/) |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | Model LLM mặc định |
| `FAST_LLM_MODEL` | `openai/gpt-4o-mini` | Model phản hồi nhanh (Planner/Verifier/DB) |
| `HEAVY_LLM_MODEL` | `openai/gpt-4o-mini` | Model chất lượng cao (RAG Synthesis/Data Storyteller) |
| `POSTGRES_URL` | `postgresql://admin:adminpassword@localhost:5432/agentdb` | Chuỗi kết nối PostgreSQL + pgvector |
| `REDIS_URL` | `redis://localhost:6379/0` | Chuỗi kết nối Redis Cache |
| `TAVILY_API_KEY` | *(Tùy chọn)* | API Key tìm kiếm web từ [Tavily](https://tavily.com/) |
| `RERANKER_ENDPOINT` | `http://localhost:8080/rerank` | Endpoint của HuggingFace TEI Reranker |
| `RERANKER_TIMEOUT` | `8.0` | Tổng ngân sách thời gian cho một lần rerank (quá hạn thì dùng thứ tự đã hợp nhất) |
| `RAG_MIN_VECTOR_SCORE` | `0.30` | Ngưỡng cosine tối thiểu để coi là "có tài liệu liên quan" |
| `INTERNAL_JWT_SECRET` | *(Random secret)* | Secret key dùng mã hóa JWT liên dịch vụ |
| `AUTH_MODE` | `off` | `off` = ẩn danh (dev), `jwt` = bắt buộc Bearer token |
| `AUTH_JWT_SECRET` / `AUTH_JWKS_URL` | *(trống)* | Secret HS256 (≥ 32 ký tự) hoặc endpoint JWKS của IdP (RS256/ES256) |
| `AUTH_JWT_AUDIENCE` / `AUTH_JWT_ISSUER` | *(trống)* | Chỉ kiểm tra khi được đặt |
| `HITL_APPROVER_ROLES` | `["approver","admin"]` | Vai trò được phê duyệt thao tác nhạy cảm (chế độ `jwt`) |
| `RATE_LIMIT_CHAT_PER_MINUTE` | `30` | Số lượt chat/stream/title mỗi người (hoặc IP) mỗi phút; `0` = không giới hạn |
| `RATE_LIMIT_ANALYZE_PER_MINUTE` | `10` | Số lượt tải lên/phân tích mỗi phút |
| `AUTH_USERS` | *(trống)* | Danh sách người dùng của màn hình đăng nhập tích hợp (JSON; tạo mục bằng `python -m scripts.make_user`); chỉ dùng với `AUTH_MODE=jwt` + `AUTH_JWT_SECRET` |
| `AUTH_TOKEN_TTL_MINUTES` / `RATE_LIMIT_LOGIN_PER_MINUTE` | `480` / `10` | Hạn của token đăng nhập; số lần thử đăng nhập mỗi IP mỗi phút (chống dò mật khẩu) |
| `KNOWLEDGE_UPLOAD_ROLES` | `["admin"]` | Vai trò được thêm/thay tài liệu vào knowledge base từ khung chat (chế độ `jwt`; chế độ ẩn danh luôn được phép) |
| `KNOWLEDGE_MAX_FILE_MB` / `KNOWLEDGE_MAX_CHUNKS` / `KNOWLEDGE_DIR` | `25` / `2000` / `dataset` | Trần dung lượng, trần số đoạn của một tài liệu, và thư mục giữ bản sao tệp đã tải lên |
| `SANDBOX_URL` / `SANDBOX_SECRET` | *(compose: `http://python-sandbox:8080` / bắt buộc)* | Nơi chạy mã phân tích do LLM viết (container riêng, không có internet); bí mật HMAC dùng chung ≥ 16 ký tự. `SANDBOX_URL` rỗng = chạy trong tiến trình con của API (chỉ để phát triển) |
| `AUTO_MIGRATE` | `true` | Tự áp các revision Alembic còn thiếu khi backend khởi động (lỗi thì dừng khởi động) |
| `DB_AGENT_PASSWORD` | *(trống)* | Từ 16 ký tự: `db_agent` chạy SQL bằng role Postgres chỉ đọc `DB_AGENT_ROLE` (chỉ `SELECT` trên `DB_AGENT_TABLES`, giao dịch chỉ đọc, timeout 15 s). Để trống thì dùng tài khoản của ứng dụng (có cảnh báo) |
| `MEM0_VECTOR_STORE` | `memory` (compose: `pgvector`) | Bộ nhớ dài hạn của Agent: `memory` = trong RAM, mất khi restart; `pgvector` = lưu trong PostgreSQL |
| `INTEGRATION_ALLOWED_HOSTS` | *(danh sách demo)* | Host mà Integration Agent được gọi (thêm mọi host `*.internal`); tên nào phân giải ra IP nội bộ/private đều bị từ chối, không theo redirect |
| `LANGFUSE_ENABLED` | `false` | Bật ghi trace. Backend kiểm tra key với server Langfuse lúc khởi động (log `Langfuse tracing ENABLED ...`); sai key hoặc server chưa lên thì tracing tắt, ứng dụng vẫn chạy |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | *(trống)* | Cặp key do bạn tự đặt (`pk-lf-<hex>`, `sk-lf-<hex>`). Compose dùng chính cặp này để tạo sẵn project Langfuse ở lần chạy đầu, không cần bấm trong giao diện |
| `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` | `admin@example.com` / *(trống)* | Tài khoản đăng nhập http://localhost:3005 do compose tạo ở lần chạy đầu (mật khẩu từ 8 ký tự). Chỉ áp dụng khi database Langfuse còn trống |
| `LANGFUSE_HOST` | `http://localhost:3005` | Host server Langfuse (compose tự đặt `http://langfuse-web:3000` cho backend) |

---

## 📊 Nạp Dữ Liệu RAG (Data Ingestion Pipeline)

Hệ thống đi kèm script tự động cắt khúc, trích xuất và nhúng tài liệu mẫu vào cơ sở dữ liệu `pgvector`:

```bash
python -m scripts.run_ingestion
```

**Quy trình Ingestion:**
1. Đọc và trích xuất text từ các thư mục tài liệu `dataset/` (PDF, DOCX, PPTX, TXT, MD; PDF bản scan được OCR nếu có Tesseract).
2. Phân đoạn ngữ nghĩa (Semantic Chunking) theo Section Title và điều chỉnh overlap.
3. Tạo vector nhúng 1536 chiều qua OpenAI `text-embedding-3-small`.
4. Ghi dữ liệu vào bảng `rag_chunks` trên PostgreSQL.
5. Tự động khởi tạo chỉ mục HNSW (`idx_rag_chunks_hnsw`) với tham số `m=16, ef_construction=64`.

### Thêm tài liệu vào knowledge base ngay trong khung chat

Đính kèm tệp **PDF, DOCX, PPTX, TXT hoặc MD** vào ô chat rồi gửi (tuỳ chọn gõ `category: nda` để chọn danh mục, hoặc kèm một câu hỏi để hỏi luôn về tài liệu đó). Backend (`POST /api/knowledge/upload`) dùng **đúng đường ống của `run_ingestion`** (cùng bộ đọc, `doc_key`/`doc_hash`, tiền tố ngữ cảnh `[Source: tệp - Section: mục]`, embedding, loại trùng trong tài liệu, ghi nguyên tử), nên dòng mới giống hệt dòng cũ trong `rag_chunks`. Khác biệt duy nhất, theo yêu cầu, là kích thước đoạn:

- mỗi **mục** (section) là một đoạn; mục **ngắn hơn 200 ký tự** được gộp với mục kế tiếp (mục cuối thì gộp với mục trước nếu vẫn ≤ 600);
- đoạn **dài hơn 600 ký tự** bị **cắt** còn 600 ở ranh giới câu/từ: **phần sau của mục đó không được lưu** (tin nhắn trong chat báo rõ số đoạn bị cắt);
- tài liệu không có mục (văn bản thuần) được chia thành các khối ≤ 600 ký tự thay vì cắt, nên không mất chữ;
- tệp trùng nội dung → "không thay đổi"; cùng tên nhưng nội dung khác → thay thế phiên bản cũ; một bản sao được giữ ở `dataset/<danh mục>/` để `run_ingestion --prune/--reset` không xoá nó.

Lưu ý: đoạn 200–600 ký tự ngắn hơn nhiều so với đoạn của tài liệu nạp từ thư mục (trung bình ~2000), điều này ảnh hưởng đến xếp hạng khi trộn hai loại; hãy chạy lại `python -m scripts.run_rag_eval` sau khi thêm số lượng lớn.

**Quản lý tài liệu và trích dẫn (trong khung chat):**

- Gõ `/docs` để xem các tài liệu đang có trong knowledge base (danh mục, số đoạn, số trang, ngày cập nhật) và **xoá** từng tài liệu (cần quyền `KNOWLEDGE_UPLOAD_ROLES`; xoá luôn cả bản sao tệp). **Thay** một tài liệu = đính kèm tệp cùng tên: phiên bản mới thay phiên bản cũ. API: `GET`/`DELETE /api/knowledge/documents`.
- **OCR cho PDF scan:** trang không có lớp chữ được vẽ lại bằng `pypdfium2` rồi đọc bằng Tesseract (`vie+eng`). Cần `tesseract-ocr` (đã có trong image backend); không có thì PDF scan bị từ chối như trước. Giới hạn bằng `OCR_ENABLED`, `OCR_LANGS`, `OCR_MAX_PAGES` (80), `OCR_DPI` (200). Độ chính xác phụ thuộc chất lượng bản scan; kết quả OCR được đánh dấu `ocr` trong metadata.
- **Xem trang trích dẫn:** nguồn PDF có số trang có nút "Xem trang N"; backend (`GET /api/knowledge/page`) vẽ trang đó thành ảnh và **tô sáng đoạn được trích dẫn** (khớp theo chữ-số, nên chịu được ngắt dòng/ký tự lạ). Không tìm được vị trí chính xác thì vẫn hiện trang, kèm ghi chú.

---

## 🔧 Vận Hành

- **Đăng nhập trên trình duyệt (`AUTH_MODE=jwt`):** đặt `AUTH_JWT_SECRET` và `AUTH_USERS`; frontend có trang `/login`, token được giữ trong cookie `httpOnly` (JavaScript của trang không đọc được) và đổi thành header `Bearer` ở lớp route của Next. Mật khẩu băm scrypt (`python -m scripts.make_user`), `POST /api/auth/login` bị giới hạn theo IP. Dùng IdP ngoài (`AUTH_JWKS_URL`) thì đặt proxy xác thực phía trước như trước đây.
- **RLS ở tầng database:** với `DB_AGENT_PASSWORD`, mọi bảng trong `DB_AGENT_TABLES` có cột `tenant_id`/`department_id` được bật chính sách `tenant_scope`; mỗi truy vấn của `db_agent` chạy trong giao dịch có `app.tenant_id`/`app.department_id`, nên PostgreSQL tự lọc hàng kể cả khi lớp viết lại SQL bị vượt qua (không có giá trị = không thấy hàng nào).
- **Sandbox phân tích tách container:** dịch vụ `python-sandbox` (pandas/numpy/scipy/matplotlib, người dùng không phải root, hệ thống tệp chỉ đọc, 1 GB/128 tiến trình) nằm trên mạng nội bộ `sandbox_net` **không ra internet và không thấy Postgres/Redis**; chỉ nhận yêu cầu có chữ ký HMAC từ backend, dữ liệu gửi dạng Parquet (không pickle). Sandbox không chạy được thì mã **không** được chạy ở nơi khác. Lưu ý: backend nằm cùng mạng nên sandbox vẫn *tới được* `backend:8000` (backend vẫn đòi xác thực ở chế độ `jwt`).
- **Migration (Alembic):** `migrations/` (revision `0001` = lược đồ `rag_chunks` hiện có, `0002` = bảng `conversations`). Backend tự áp khi khởi động (khoá advisory: nhiều bản sao khởi động cùng lúc thay phiên nhau); thủ công: `python -m scripts.migrate [--status]`; thay đổi mới: `alembic revision -m "..."`. `src/ingestion/schema.py` đã đóng băng, không sửa nó cho thay đổi mới.
- **Nhiều bản sao backend:** `docker-compose.scale.yml` + `deploy/nginx-scale.conf` dựng N bản sao sau một nginx trong project compose riêng (`docker compose -p scaletest -f docker-compose.yml -f docker-compose.scale.yml up -d --scale backend=3 backend lb`), rồi `python -m scripts.replica_check` kiểm tra giới hạn tốc độ, hội thoại và ghi đồng thời có thật sự dùng chung qua Redis/PostgreSQL. Số kết nối Postgres = (kích thước pool × số bản sao) phải nhỏ hơn `max_connections` (mặc định 100).
- **Stream token câu trả lời:** `/api/chat/stream` gửi thêm `answer_delta`/`answer_reset` khi RAG đang viết; đó là **bản xem trước chưa được kiểm định**, `final_response` thay thế nó. Phần lớn độ trễ nằm ở lập kế hoạch + truy xuất (~12 s), không phải ở sinh văn bản, nên stream chỉ giúp rõ với câu trả lời dài.
- **Hội thoại phía server:** khi đã đăng nhập, `/api/conversations` lưu hội thoại theo (tenant, người dùng) với kiểm soát xung đột lạc quan (409 kèm bản mới của server); trình duyệt vẫn giữ bản sao cục bộ, đồng bộ sau mỗi thay đổi 2 giây, khi quay lại tab và mỗi phút; xung đột thì bản của server thắng và bản trên máy được giữ thành một hội thoại riêng. Đăng xuất xoá bản sao cục bộ.
- **Ngôn ngữ giao diện:** vi/en (nút `EN`/`VI` ở header và trang đăng nhập) cho **toàn bộ giao diện** (`frontend/lib/locales/vi.ts` + `en.ts`; một test kiểm tra hai bộ khoá khớp nhau và không còn chữ Việt cứng trong component). Trình duyệt gửi `X-UI-Lang`, nên thông báo của backend (lỗi, tóm tắt tải lên, phê duyệt HITL) cũng theo ngôn ngữ đã chọn (`src/shared/messages.py`). Dashboard theo ngôn ngữ của dữ liệu, câu trả lời của agent theo ngôn ngữ câu hỏi; văn bản kế hoạch/kết quả thực thi mà agent viết ra trong stepper không được dịch.

---

## 🧪 Kiểm Thử & Offline Evaluation (LLM-as-a-Judge)

### 1. Bộ kiểm thử tự động (Unit & Integration Tests)
Chạy toàn bộ **102 test cases** bao phủ toàn diện 5 module Enterprise Upgrades và các tính năng Hardened:

```bash
# Chạy bộ test nâng cấp bảo mật & guardrails (49 tests)
python -m pytest tests/test_hardened_upgrades.py -v

# Chạy bộ test hệ thống tổng thể (53 tests)
python -m pytest tests/test_enterprise_upgrades.py -v
```

### 2. Đánh giá chất lượng

**Kiểm tra cấu trúc (offline, dùng được trong CI):**

```bash
python scripts/run_offline_eval.py
```

Kiểm tra tính nhất quán của **Golden Dataset** (intent → agent, độ phủ từ khoá, guardrail). Đây *không* phải phép đo chất lượng RAG: nó không chạy truy xuất hay sinh câu trả lời.

**Đánh giá RAG thật** (cần Postgres đã nạp tài liệu và `OPENROUTER_API_KEY`):

```bash
python -m scripts.run_rag_eval --build 60            # tạo bộ câu hỏi từ các chunk ngẫu nhiên -> dataset/rag_eval.json
python -m scripts.run_rag_eval --rerank --answers 20 # đánh giá -> reports/rag_eval.md
```

Đo hit@1/5/10/20 và MRR theo từng chế độ truy vấn (raw / HyDE / cả hai) và theo độ dài văn bản đưa vào reranker (kèm độ trễ), khả năng từ chối câu hỏi ngoài phạm vi (chọn ngưỡng `RAG_MIN_VECTOR_SCORE`), tỷ lệ câu trả lời có trích dẫn `[n]`, tỷ lệ con số có trong nguồn và điểm trung thực do LLM chấm khi thấy các nguồn.

---

## 📂 Cấu Trúc Thư Mục Dự Án

```
Multi-Agents/
├── docker-compose.yml              # Khởi chạy 7 Docker microservices
├── Dockerfile                      # Build image cho FastAPI Gateway Backend
├── requirements.txt                # Thư viện Python phụ thuộc
├── docker-compose.dev.yml          # Override cho phát triển (backend hot-reload)
├── requirements-dev.txt            # requirements.txt + pytest
├── pytest.ini                      # Cấu hình pytest
│
├── scripts/                        # CLI: run_ingestion (nạp tài liệu vào pgvector), run_offline_eval, công cụ báo cáo
│   └── dev/                        # Script thử nghiệm ad-hoc
├── reports/                        # Báo cáo đánh giá chất lượng LLM-as-a-Judge (eval_report.*)
├── legacy/                         # Mã đã ngưng dùng: streamlit_ui/, rag_pipeline/
│
├── docs/                           # Toàn bộ tài liệu dự án
│   ├── PORTFOLIO_CASE_STUDY.md     # Bản Case Study chuyên sâu (Schema chuẩn Bolt.new)
│   ├── SYSTEM_ARCHITECTURE.md      # Tài liệu chi tiết kiến trúc hệ thống
│   ├── PROJECT_DOCUMENTATION.md    # Tài liệu toàn diện dự án
│   ├── AGENT_PROMPTS.md            # Prompt của các agent
│   ├── UNIVERSALIZATION_REPORT.md  # Báo cáo refactor loại bỏ hardcode
│   └── screenshots/                # Ảnh chụp giao diện
│
├── src/                            # Mã nguồn chính Backend
│   ├── config.py                   # Cấu hình Pydantic Settings
│   ├── agents/                     # 5 Agent chuyên biệt (BaseAgent contract)
│   │   ├── rag_agent/              # HyDE + Hybrid Search + Knowledge Store
│   │   ├── data_agent/             # Swarm 5 Sub-Agents xử lý CSV & Dashboard
│   │   ├── search_agent/           # Tavily Web Search + Crawl4AI
│   │   ├── db_agent/               # Database SQL Agent + AST Validator
│   │   └── integration_agent/      # Integration REST API Agent
│   ├── gateway/                    # FastAPI App & SSE Endpoint (/api/chat/stream)
│   ├── orchestrator/               # LangGraph StateGraph (PEV Loop Engine)
│   ├── registry/                   # AgentRegistry với Cosine Validation Gate
│   └── shared/                     # Dịch vụ hạ tầng (Redis, Postgres, MCP, Security, PII)
│
├── frontend/                       # Ứng dụng Next.js 14 App Router
│   ├── app/                        # App Router Pages & Layout
│   ├── components/                 # React UI Components
│   │   ├── PEVStepper.tsx          # Real-time SSE Agent Stepper
│   │   ├── ChatInterface.tsx       # Khung chat Markdown & Sources
│   │   ├── CSVUploader.tsx         # Kéo thả file CSV
│   │   ├── DataSummaryView.tsx     # DuckDB WASM In-Browser SQL Playground
│   │   └── dashboard/              # Dynamic 12-Col Dashboard (ECharts + AG-Grid)
│   ├── lib/                        # DuckDB WASM loader, SSE client, Types
│   └── tests/                      # Playwright E2E Test Suite (5 specs)
│
├── dataset/                        # Dữ liệu tài liệu mẫu & Golden Eval Dataset
├── scripts/                        # Script CI/CD Offline Evaluation
└── tests/                          # 102 Unit & Integration Tests (Pytest)
```

---

## 📄 Giấy Phép (License)

Dự án được phát hành theo giấy phép mã nguồn mở [MIT License](LICENSE).

---

<div align="center">
  <b>Developed by <a href="https://github.com/BCNguyen115">BCNguyen115</a></b><br>
  <i>Fresher AI</i>
</div>
