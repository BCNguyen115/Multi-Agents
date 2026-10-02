# Đánh giá toàn diện và lộ trình nâng cấp

Ngày đánh giá: 2026-09-30. Phạm vi: backend (FastAPI/LangGraph), frontend (Next.js 14), triển khai (Docker Compose), bộ nhớ của Agent.

**Đã đọc:** cấu hình triển khai, gateway, orchestrator, các lớp bảo mật, các client dùng chung, cấu trúc frontend, `package.json`, bộ test. **Chưa làm:** đọc chi tiết từng component React, kiểm thử tải, kiểm thử xâm nhập. Những điểm chưa xác minh được đều ghi rõ trong bảng bên dưới.

## 0. Trạng thái triển khai (cập nhật 2026-09-30)

Đã làm theo thứ tự lộ trình "Tuần 1–2" (mục 6), mỗi mục có test và, nếu có thể, đã kiểm chứng trên dịch vụ thật:

| Hạng mục | Kết quả | Kiểm chứng |
|---|---|---|
| Bộ nhớ Agent: mem0 chạy trong thread có timeout thật; ghi câu hỏi thật thay vì nhật ký định tuyến (mục 3.3, bước 1–2) | Xong | `tests/test_agent_memory.py` + backend thật: lượt 1 ghi "tên/phòng ban", lượt 2 truy xuất được 1 bộ nhớ (trước đây 6/6 lượt đều 0); `/health` chậm nhất 0,09 s trong lúc chat và ghi bộ nhớ (trước đây loop đứng 2,4–11 s) |
| Xác thực Bearer JWT (HS256 hoặc JWKS), phiên gắn với người dùng, vai trò phê duyệt HITL + nhật ký, tenant/phòng ban từ token | Xong, **mặc định tắt** (`AUTH_MODE=off`) | `tests/test_auth.py` (19 test) + backend thứ hai chạy `AUTH_MODE=jwt`: 401 khi thiếu/sai/hết hạn token, Redis có `history:alice:sess-1` và `history:bob:sess-1` tách biệt, phê duyệt 403 khi thiếu vai trò |
| RLS: `AND` thay `OR`; **fail-closed** khi chèn RLS lỗi (trước đây âm thầm chạy SQL không có RLS) | Xong | `tests/test_architectural_upgrades.py` |
| Giới hạn tốc độ theo người dùng/IP (Redis) | Xong | `tests/test_rate_limit.py` + Redis thật: 3 lượt qua, lượt 4–5 nhận 429 kèm `Retry-After` |
| Trần tải lên: từ chối theo `Content-Length` trước khi đọc, đọc theo khối | Xong | `tests/test_auth.py` (middleware). Chưa thử tải tệp lớn thật |
| Đóng cổng 8000 (chỉ 127.0.0.1) | Xong | Đã áp dụng: `agent_backend` chỉ nghe `127.0.0.1:8000` |
| Từ chối khởi động khi secret mặc định/yếu (chế độ `jwt`) | Xong | `tests/test_auth.py` |
| `/ready` (Postgres, Redis, reranker) | Xong | `tests/test_readiness.py` + gọi thật: `ready` (Postgres, Redis, reranker đều `ok`) |
| Xoá thư viện thừa `@tremor/react` | Xong | `tsc`, lint, 23 test vitest đạt; build image frontend (chạy `next build`) thành công |
| Khoá phụ thuộc (`requirements.lock`, Dockerfile dùng `-c`) | Xong về mặt tệp | Khoá lấy từ image đang chạy; build lại image backend với `-c requirements.lock` thành công và stack chạy bình thường |
| CI cơ bản (`.github/workflows/ci.yml`) + ruff tối thiểu | Đã viết | Ruff chạy sạch cục bộ, YAML hợp lệ; **chưa chạy trên GitHub**, lần chạy đầu là phép thử thật |

Frontend: các route handler của Next (`stream`, `analyze`, `filter`, `title`) đã chuyển tiếp header `Authorization` (`frontend/lib/backendAuth.ts`, 2 test); đã thử qua cổng 3001 với `AUTH_MODE=off`, kể cả khi có header đó.

Toàn bộ test backend: 457 đạt, 1 bỏ qua (test DB thật cần `RAG_TEST_DSN`).

**Phát hiện thêm khi làm:** planner RAG vẫn có lúc dịch câu hỏi tiếng Việt ngắn sang tiếng Anh (ví dụ "Tôi làm ở phòng nào?" → "What department do I work in?"); câu trả lời vẫn theo ngôn ngữ người dùng gõ nhưng truy xuất dùng bản dịch. Chưa xử lý.

### Đợt tiếp theo (cùng ngày)

| Hạng mục | Kết quả | Kiểm chứng |
|---|---|---|
| Planner không còn dịch câu hỏi tiếng Việt sang tiếng Anh | Xong: chỉ dẫn rõ trong prompt + kiểm tra ngôn ngữ đầu ra bằng `detect_language` (nếu vẫn dịch thì giữ nguyên câu người dùng) | `tests/test_rag_agent.py` |
| Gỡ `MemorySaver` (chỉ tích luỹ mọi checkpoint, kể cả nội dung CSV, của mọi phiên trong RAM) | Xong, **sau một hồi quy do tôi gây ra**: lần gỡ đầu bỏ sót việc đường SSE đọc trạng thái cuối bằng `aget_state`, làm `/api/chat/stream` trả `error: No checkpointer set` (phát hiện khi thử qua cổng 3001, không phải bởi test). Nay trạng thái cuối được dựng từ cập nhật của từng node | `tests/test_orchestrator_graph_paths.py` (chạy đồ thị thật qua cả hai đường JSON và SSE) + stream thật qua cổng 3001 trả `final_response` |
| Phê duyệt HITL trong Redis (`hitl:pending:<id>`, TTL, nhận đúng một lần, sai phiên không làm mất) | Xong | `tests/test_hitl_shared_state.py` (hai bản sao dùng chung Redis, restart, Redis lỗi thì dùng bản cục bộ) |
| Bộ nhớ dài hạn bền vững (mem0 + pgvector, `MEM0_VECTOR_STORE=pgvector` trong compose) và theo người dùng (`<tenant>:<user>` khi đã xác thực) | Xong | Backend thật: ghi bộ nhớ, `docker restart agent_backend`, lượt sau truy xuất được 1 bộ nhớ; container Postgres riêng: người dùng khác thấy rỗng |
| Role Postgres chỉ đọc cho `db_agent` (`DB_AGENT_PASSWORD`, SELECT chỉ trên `knowledge_documents`, giao dịch chỉ đọc, timeout 15 s), fail-closed khi không tạo được | Xong; mật khẩu ngẫu nhiên đã được thêm vào `.env` của bạn | `tests/test_db_roles.py` (gồm test thực thi thật trên Postgres) + backend thật: `rag_chunks`, `langfuse.users` bị `InsufficientPrivilege`, INSERT/DROP/CREATE bị từ chối |
| SSRF: danh sách host cấu hình được (`INTEGRATION_ALLOWED_HOSTS`), không theo redirect, từ chối tên hợp lệ nhưng phân giải ra IP private/metadata | Xong | `tests/test_ssrf_guards.py` (DNS và HTTP giả lập) + container thật: `follow_redirects=False`, IP metadata bị allow-list chặn, tên hợp lệ phân giải ra `10.0.0.5` bị từ chối trước khi gửi |

Giới hạn còn lại của phần SSRF: địa chỉ được kiểm tra rồi HTTP client phân giải lại (DNS rebinding giữa hai lần chưa chặn được); muốn chặn hẳn cần transport ghim IP. Danh sách mặc định vẫn có các host demo (`example.com`, `httpbin.org`, `jsonplaceholder.typicode.com`): production nên đặt danh sách riêng.

**Vận hành (bài học trong ngày):** mỗi lần build image backend nặng ~4 GB vì `torch` kéo theo các wheel CUDA (nvidia_*), và Docker Desktop dùng ~117 GB trong WSL; các lần build liên tiếp làm đầy ổ C: khiến Docker treo và phải khởi động lại. Nên dọn định kỳ (`docker builder prune`, `docker image prune`). **Đã xử lý phần torch:** mã không import `torch` (chỉ `sentence-transformers`, một extra tuỳ chọn của mem0, kéo nó vào; embedding đi qua API), nên Dockerfile cài `torch` bản CPU trước (phiên bản lấy từ `requirements.lock`) và pip bỏ qua toàn bộ `nvidia-*`/`triton`: image backend từ 13 GB xuống 5,45 GB, venv còn 2,8 GB; mem0/pgvector, SSRF, role chỉ đọc và `/ready` vẫn đúng trên container mới. `pip install` trong Dockerfile nay có timeout 120 s và thử lại 5 lần vì lần tải wheel lớn từng hết hạn.

**Kiểm thử tải (`python -m scripts.loadtest`):** 20 người gọi đồng thời trong 10 s: `/health` p50 32 ms, p95 93 ms; `/ready` p95 125 ms; 328 yêu cầu/s, không lỗi. 5 lượt chat chồng nhau: cả 5 trả 200, ~6,4 s mỗi lượt, trong lúc đó `/health` p95 31 ms (event loop không bị chặn). Đây là tải nhẹ trên một máy với một bản sao backend, chưa phải đo công suất tối đa; lượt chat chạy với câu ngoài phạm vi (rẻ nhất) nên chưa phản ánh độ trễ của câu trả lời đầy đủ (13–21 s).

### Đợt thứ ba (2026-10-01)

| Hạng mục | Kết quả | Kiểm chứng |
|---|---|---|
| Tải tài liệu vào knowledge base ngay trong chat | PDF/DOCX → mỗi mục một đoạn, mục < 200 ký tự gộp với mục kế tiếp, đoạn > 600 bị cắt (báo rõ trong chat), cùng đường ống/cột/tiền tố ngữ cảnh/embedding như `run_ingestion` | 27 test; thử thật: DOCX và PDF (64 đoạn), hỏi lại có trích dẫn ngay; Chromium: tải DOCX qua ô chat rồi hỏi |
| Đăng nhập trên trình duyệt | `/login`, mật khẩu scrypt (`make_user`), JWT trong cookie httpOnly, giới hạn thử theo IP | curl + Chromium (cookie httpOnly, JS không đọc được token, đăng xuất xoá bản sao cục bộ). **Lỗi tìm ra nhờ trình duyệt:** rewrite `/api/*` của Next chặn route động `[id]` (xét trước route handler) làm mất header Bearer → đã chuyển sang `fallback` |
| RLS ở tầng database | policy `tenant_scope` + giao dịch `set_config(app.*)`; không có giá trị thì không thấy hàng nào | test trên Postgres thật (hai tenant, SQL không có WHERE) |
| Sandbox phân tích trong container riêng | `python-sandbox` thật (pandas/numpy), mạng nội bộ, HMAC, Parquet, fail closed | không ra internet, không thấy Postgres/Redis, ghi đĩa bị chặn; câu hỏi dữ liệu thật trả đúng số. **Lỗi Linux-only tìm ra khi giả lập CI:** worker bị giết bởi `RLIMIT_CPU` trước hạn của cha → báo sai thông báo; đã sửa |
| Alembic | `0001` (baseline) + `0002` (conversations), tự áp khi khởi động, khoá advisory | 4 tiến trình khởi động đồng thời trên DB trống |
| Hội thoại phía server | `/api/conversations` (tenant+user, 409 kèm bản server, so sánh theo mili-giây), đồng bộ trình duyệt | 6 lần ghi đồng thời: đúng 1 thắng; Chromium: hội thoại lên server và hiện ở trình duyệt thứ hai |
| Stream token | `answer_delta`/`answer_reset` (bản xem trước chưa kiểm định) | 35 sự kiện, bản xem trước = câu trả lời cuối; **token đầu ở giây 16,1/16,6**: độ trễ nằm ở truy xuất, không ở sinh văn bản |
| i18n/a11y | vi/en cho khung giao diện và tính năng mới; nhãn nút, liên kết bỏ qua điều hướng | unit test; chưa đo điểm Lighthouse (công cụ cần Chrome stable, máy không có) |
| Next 15 / React 19 | + `ag-grid` 32, `lucide-react` 1.x (cài sạch, không cần cờ ép peer) | tsc/lint/52 test/build; Chromium: dashboard 8 canvas + bảng AG Grid, không lỗi console |
| Nhiều bản sao backend | `docker-compose.scale.yml` + nginx + `replica_check` | 3 bản sao: giới hạn tốc độ, hội thoại, ghi đồng thời đều dùng chung; 505 so với 264 yêu cầu/s trên một bản (máy đã bão hoà, chỉ là chỉ báo). **Lỗi tìm ra:** khởi động đồng thời trên DB trống tranh nhau `CREATE EXTENSION`/schema → khoá advisory (cũ hỏng 6/6, mới đạt) |
| Dọn code | `core.py` 1579 → 1037 dòng (`approvals.py`, `streaming.py`, `common.py`), schema gateway ra `schemas.py`, `ChatInterface.tsx` 867 → 650 (`pevTrace.ts`), bỏ `recharts` | toàn bộ test |
| CI | thêm CPU torch, `compose config`, build image sandbox; sửa lỗi YAML | giả lập từng job trong container Linux: 564 test backend, frontend đạt |

**Còn lại / hạn chế (nói thẳng):**
- CI **chưa chạy trên GitHub thật**; chỉ giả lập cục bộ (xem chú thích đầu `ci.yml`).
- `core.py` (~1000 dòng, các node planner/executor/verifier) và `main.py` (~1060 dòng, các route) vẫn lớn: tách tiếp cần đổi cách test monkeypatch các biến toàn cục.
- Sandbox vẫn *tới được* `backend:8000` vì chung mạng nội bộ (backend vẫn đòi xác thực ở chế độ `jwt`).
- i18n mới phủ khung giao diện và tính năng mới; các màn khác vẫn tiếng Việt. Stream chỉ cho RAG.
- Đo tải nhiều bản sao: một máy bão hoà, chưa đo lượt chat LLM đồng thời nhiều bản sao; số kết nối Postgres = pool × số bản sao phải nhỏ hơn `max_connections`.
- Đoạn 200–600 ký tự ngắn hơn nhiều so với đoạn nạp từ thư mục (~2000): cần chạy lại `run_rag_eval` sau khi thêm số lượng lớn tài liệu.
- Cache dữ liệu phân tích của data_agent vẫn theo tiến trình.

### Đợt thứ tư (2026-10-01): nhóm B (chất lượng knowledge base), i18n toàn giao diện, chuẩn hoá Langfuse

| Hạng mục | Kết quả | Kiểm chứng |
|---|---|---|
| Quản lý tài liệu từ chat | `/docs` liệt kê và xoá tài liệu (`GET/DELETE /api/knowledge/documents`, quyền `KNOWLEDGE_UPLOAD_ROLES`); thay tài liệu = tải lại cùng tên | test backend + Chromium |
| Thêm định dạng | PPTX, TXT, MD; PDF scan qua OCR (pypdfium2 + Tesseract `vie+eng`) | 26 test `test_kb_manage.py` chạy cả trong image Linux, gồm lần đọc ảnh scan thật bằng Tesseract |
| Xem trang PDF có tô sáng đoạn được trích | nút "Xem trang" ở nguồn trích dẫn (`/api/knowledge/page`) | test + Chromium |
| Contextual retrieval | **Đã đo, không bật**: hit@5 0.520 so với 0.587, MRR 0.386 so với 0.443 (có rerank 0.600 so với 0.653 và 0.492 so với 0.531) | `run_rag_eval` trên DB scratch, chi tiết ở `docs/RAG_REVIEW_AND_FIXES.md` |
| Cổng chất lượng truy xuất trong CI | job `rag-eval` chạy tay (`workflow_dispatch`), ngưỡng hit@5 0.55 và MRR 0.40 | chỉ chạy lệnh cục bộ, **chưa chạy trên GitHub** |
| i18n vi/en toàn bộ giao diện | mọi chuỗi qua `t(lang, key)`; từ điển có test khớp khoá và `{placeholder}`, test cấm chữ Việt cứng trong `app/`, `components/`, `lib/`; thông báo của backend cũng theo ngôn ngữ (header `X-UI-Lang`) | 54 test frontend, tsc, lint, `next build`; test HITL hai ngôn ngữ |
| Chuẩn hoá Langfuse | xem bên dưới | 8 test `test_tracing.py` + chạy thật: một request chat = một trace đủ planner/executor/verifier và các lần gọi LLM |

**Langfuse: những gì tìm ra khi kiểm tra thật.** (1) Server chưa có project hay key nào (0 project, 0 api_keys) nên mọi lần ghi trace đều bị 401, trong khi log backend vẫn ghi "Langfuse tracing ENABLED and verified": bản cũ chỉ kiểm tra chuỗi key có phải giá trị mẫu hay không, không hỏi server. (2) Handler LangGraph của SDK V2 không import được trên `langchain` 1.x (`langchain.callbacks` đã bị bỏ), nên `get_langfuse_callback` luôn trả `None`: cây trace của orchestrator chưa từng được ghi. (3) Mỗi request dựng một client Langfuse mới (kèm thread nền), và `flush()` dựng thêm một client nữa. (4) Một lần gọi LLM lỗi bất kỳ tắt tracing của cả tiến trình vĩnh viễn. (5) Mỗi lần gọi LLM mở trace riêng, tách khỏi trace của orchestrator.
**Đã sửa:** `src/shared/tracing.py` kiểm tra key bằng `auth_check()` (thử lại 3 lần để chờ server lên; sai key thì tắt tracing và ứng dụng vẫn chạy), một client dùng chung, bí danh module cho handler của SDK V2, mỗi request một trace chứa cả các lần gọi LLM (`existing_trace_id` qua ContextVar), bỏ cơ chế tắt tracing khi một lần gọi lỗi và danh sách host dự phòng. Compose tự tạo org/project/key/tài khoản quản trị Langfuse ở lần chạy đầu từ `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_INIT_USER_*` (chỉ khi DB Langfuse còn trống), thêm healthcheck cho `langfuse-web`, backend chờ nó nhưng không bị chặn (`required: false`). Đã thử: `langfuse-web` vẫn khởi động bình thường khi các biến này để trống.

**Hạn chế (nói thẳng):**
- Job `rag-eval` và toàn bộ CI vẫn **chưa chạy trên GitHub thật**.
- Độ chính xác OCR phụ thuộc chất lượng bản scan; mới thử một trang scan tổng hợp, chưa thử tài liệu scan thật.
- Chữ do agent viết (kế hoạch/kết quả hiển thị trong stepper, một số chuỗi plan của backend) không được dịch; các component không còn dùng (`WorkspaceLayout`, `AgentSelectorInChat`, `AgentThoughtStepper`) đã dịch nhưng vẫn là mã chết.
- Contextual retrieval chỉ được đo trên một kho (hợp đồng/SOW); nguyên nhân kém hơn chưa được kiểm chứng.
- Langfuse: biến `LANGFUSE_INIT_*` chỉ có tác dụng khi DB Langfuse còn trống; đổi key về sau phải làm trong giao diện Langfuse (và sửa `.env` cho khớp). Trace gắn qua ContextVar theo từng request; chưa kiểm tra với nhiều request chạy song song.

## 1. Nhận định chung

- **Điểm mạnh:** kiến trúc tách lớp rõ; lớp bảo mật nhiều tầng (chống prompt injection, sqlglot allow-list, HITL, sandbox có AST allow-list); dữ liệu tài liệu có bộ đánh giá đo được (`scripts/run_rag_eval.py`, xem `docs/RAG_REVIEW_AND_FIXES.md`); 422 test backend đạt.
- **Điểm yếu lớn nhất:** hệ thống vẫn là một người dùng, một tiến trình. Nhiều cơ chế "doanh nghiệp" (tenant, RLS, HITL, bộ nhớ dài hạn) chưa gắn với danh tính thật và giữ trạng thái trong RAM.
- **Quy mô:** backend ≈ 13,9 nghìn dòng Python, frontend ≈ 8,8 nghìn dòng TS/TSX; 422 test backend, 21 test đơn vị + 5 spec e2e phía frontend.

## 2. Backend

### 2.1. P0 — An toàn và danh tính

| Vấn đề (bằng chứng) | Đề xuất |
|---|---|
| **Không có xác thực.** `src/gateway/main.py` không có dependency xác thực nào; `session_id` do client tự gửi. Cổng 8000 được publish ra mọi interface trong `docker-compose.yml`, trong khi Postgres/Redis chỉ bind 127.0.0.1 | Middleware OIDC/JWT; gắn `session_id` vào user; đóng cổng 8000 sau reverse proxy |
| **HITL không gắn người duyệt.** `src/orchestrator/core.py` (`handle_approval_decision`) chỉ kiểm tra `action_id` + `session_id`; ai biết hai giá trị này đều duyệt được thao tác ghi/SQL nhạy cảm | Ràng buộc với user và vai trò; ghi nhật ký kiểm toán (ai duyệt, lúc nào) |
| **Tenant tĩnh.** `src/config.py` dùng một `tenant_enterprise` cố định. Theo docstring của `rls_transformer.py`, predicate là `department_id = … OR tenant_id = …`, tức phạm vi **rộng hơn** bằng chứng, dùng OR thay vì AND | Lấy tenant/phòng ban từ token; đổi sang AND; RLS thật ở tầng Postgres |
| **Quyền DB của `db_agent`:** chưa xác minh được nó dùng riêng role nào. Langfuse cũng nằm chung database `agentdb` | Dùng role chỉ đọc, chỉ cấp quyền trên các bảng được phép; tách database hoặc schema |
| **Không giới hạn tốc độ / chi phí.** Mỗi lượt chat gọi gpt-4o, planner, reranker | Rate limit theo user, ngân sách token/ngày, semaphore cho LLM và reranker |
| **Upload đọc cả file vào RAM rồi mới kiểm tra kích thước** (`/api/analyze`) | Kiểm tra `Content-Length` và đọc theo khối có trần |
| **SSRF allow-list** (`src/shared/mcp_client.py`) chứa `example.com`, `httpbin.org` và mọi host `*.internal`, không kiểm tra IP đích hay redirect | Đưa danh sách vào cấu hình, chặn IP private, tắt redirect |
| **Sandbox chạy trong chính container backend.** Container `python-sandbox` không có mạng có trong compose nhưng không thấy được dùng. Trên Windows không có rlimit | Chạy worker phân tích trong container đó (hoặc gVisor/nsjail) |
| `.env.example` có sẵn `INTERNAL_JWT_SECRET=your-enterprise-secret-key-change-me` | Từ chối khởi động nếu còn giá trị mặc định ngoài chế độ dev |

### 2.2. P1 — Độ tin cậy và khả năng mở rộng

- **Trạng thái nằm trong RAM:** `MemorySaver`, `pending_approvals`, cache dữ liệu phân tích. Khởi động lại là mất các yêu cầu duyệt đang chờ, và không chạy được nhiều bản sao. Đưa vào Redis/Postgres (LangGraph có checkpointer Postgres/Redis).
- **Health check quá nông:** `/health` luôn trả `ok`. Thêm `/ready` kiểm tra Postgres, Redis, reranker và LLM.
- **Nuốt lỗi:** 95 chỗ `except Exception`. Việc dự phòng (planner, reranker, mem0…) hiện im lặng; thêm bộ đếm để thấy khi nào hệ thống đang chạy ở chế độ suy giảm.
- **Độ trễ RAG 13–21 s mỗi câu** (rerank CPU 4,2 s, planner 2,8 s, phần còn lại là sinh câu trả lời). Đòn bẩy: stream token của câu trả lời qua SSE (giảm thời gian chờ cảm nhận), reranker nhỏ hơn hoặc GPU, cache câu trả lời cho câu hỏi lặp.
- **Module quá lớn:** `core.py` 1.478 dòng và `main.py` 941 dòng (planner, executor, verifier, HITL và DAG chung một file; các route chung một file). Tách thành router và service.
- **Schema DB tự migrate bằng `ensure_schema`.** Nên dùng Alembic khi có nhiều môi trường.

## 3. Bộ nhớ của Agent (mem0) — kiểm tra ngày 2026-09-30

### 3.1. Đã kiểm tra

- **RAM backend bình thường:** 808 MiB / 7,6 GiB, 0 lần restart, không OOM. Reranker dùng 1,9 GiB.
- **mem0 khởi tạo được và cơ chế lưu/tìm hoạt động:** thử với một sự kiện thật ("Tôi tên Nguyên, làm ở phòng pháp chế…") thì mem0 lưu được và tìm lại được.
- **Lịch sử hội thoại của RAG trong Redis hoạt động** (câu hỏi nối tiếp được viết lại đúng trong các lượt thử end-to-end).

### 3.2. Lỗi phát hiện

| # | Vấn đề | Bằng chứng |
|---|---|---|
| 1 | **Bộ nhớ luôn rỗng.** Backend ghi chuỗi `User asked: '<user_untrusted_input nonce=…>…' -> Target Agent: 'rag_agent'`. mem0 dùng LLM để trích sự kiện từ chuỗi này nên không rút ra gì | Thử đúng định dạng đó cho `results: []`. Log backend: 6/6 lượt truy xuất đều "Retrieved 0 long-term memories"; khối "Long-term memories" mà planner nhận luôn là "None" |
| 2 | **Mỗi lần ghi làm treo toàn bộ API.** `add_memory` và `get_relevant_memories` (`src/shared/memory_manager.py`) gọi mem0 **đồng bộ** (có gọi LLM/embedding) ngay trên event loop | Đo được event loop đứng 2,4 s (lần không lưu được gì) đến 11 s (lần lưu được); mọi người dùng khác phải chờ |
| 3 | **Không bền vững.** Vector store là Qdrant `:memory:` (`memory_manager.py`); mất hết khi restart | Log khởi động mỗi lần đều tạo lại collection `mem0` |
| 4 | **Bộ nhớ gắn với `session_id`, không gắn với người dùng** (`user_id=session_id`), nên không bao giờ "nhớ" xuyên các cuộc hội thoại | Gốc rễ là chưa có danh tính (mục 2.1) |
| 5 | Khi mem0 lỗi, hệ thống âm thầm chuyển sang `_fallback_store`, cũng nằm trong RAM | Không có bộ đếm hay cảnh báo cho thấy đang ở chế độ này |

**Ghi chú về một thay đổi trước đó:** lỗi #2 vốn có sẵn. Việc đưa `add_memory` vào tác vụ nền với `asyncio.wait_for(..., 30)` (trong `Orchestrator._remember_in_background`) **không có tác dụng thật**: lời gọi mem0 chạy đồng bộ ngay khi được gọi nên vẫn chặn loop và `wait_for` không ngắt được. Ghi chú "chạy nền, giới hạn 30 s" trong `docs/RAG_REVIEW_AND_FIXES.md` (mục 2) không đúng và cần được sửa cùng với lỗi này.

### 3.3. Đề xuất sửa

1. **Ngay (nhỏ):** chạy các lời gọi mem0 qua `asyncio.to_thread` (ghi và tìm), để API không còn bị chặn và timeout mới có tác dụng.
2. **Ngay (nhỏ):** ghi nội dung có giá trị để mem0 trích được sự kiện, tức là câu hỏi thật của người dùng đã bỏ lớp nonce (và tuỳ chọn tóm tắt câu trả lời), thay vì chuỗi nhật ký định tuyến. Không lưu nội dung tài liệu nhạy cảm.
3. **Sau khi có xác thực:** dùng `user_id` thật; vector store bền vững (pgvector hoặc Qdrant server); bộ đếm ghi thành công / rơi vào chế độ dự phòng / độ trễ ghi; chính sách xoá và hết hạn bộ nhớ theo người dùng.
4. **Kiểm thử:** thêm test tích hợp (ghi một sự kiện, lượt sau truy xuất lại được) và test kiểm tra event loop không bị chặn khi ghi bộ nhớ.

## 4. Frontend

| Vấn đề (bằng chứng) | Đề xuất |
|---|---|
| **Hai nguồn sự thật cho lịch sử chat:** localStorage (`app/page.tsx`, `lib/storage.ts`) và Redis phía backend; đổi trình duyệt là mất hội thoại | API hội thoại phía server (liệt kê, lấy, xoá) gắn với user; localStorage chỉ làm cache |
| **Component quá lớn, state cục bộ:** `ChatInterface.tsx` 804 dòng, `Sidebar.tsx` 496, `DynamicDashboard.tsx` 468, `PEVStepper.tsx` 454, mỗi file 8–14 hook | Tách hook (`useChatStream`, `useSessions`), dùng store (Zustand) hoặc React Query cho dữ liệu từ server |
| **Thư viện thừa:** `@tremor/react` không được import ở đâu; `recharts` chỉ 1 file trong khi đã có `echarts` | Xoá tremor, gộp về echarts; `pptxgenjs`, `duckdb-wasm` chỉ nạp khi cần; đo bằng bundle analyzer |
| **Proxy không thống nhất:** vừa có rewrite `/api/*` ở `next.config.mjs`, vừa có route handler riêng cho stream/analyze/title | Chọn một cách; nơi nào cần chèn token xác thực thì dùng route handler |
| **SSE thiếu bền vững:** `lib/sse.ts` không tự kết nối lại, không phát lại sự kiện; sự kiện phê duyệt dùng `as any` (tổng cộng 16 chỗ `any`/`ts-ignore`) | Kết nối lại có backoff; kiểm tra kiểu payload bằng zod |
| **Test mỏng:** 3 file unit (216 dòng, chỉ phần thư viện thuần) và 5 spec e2e; component gần như chưa có test | Testing Library cho luồng stream, `ApprovalCard`, `SourcesList`; chạy e2e trong CI với backend giả |
| **A11y và i18n:** khoảng 23 thuộc tính `aria-`/`role=` trên toàn bộ component; chuỗi tiếng Việt cứng trong code | Kiểm tra axe trong Playwright; `next-intl`; vùng `aria-live` cho nội dung đang stream |
| **Phụ thuộc cũ:** Next 14.2.3, React 18 | Lập kế hoạch nâng lên Next 15+ sau khi có test bảo vệ |

Gợi ý tính năng: nút "dừng sinh", nút thích/không thích (làm nguồn bổ sung cho bộ đánh giá RAG), hiển thị thời gian từng bước (planner/rerank/sinh), xuất hội thoại.

## 5. DevOps và kho mã

- **Không có CI** (không có `.github`), không có ruff/mypy, và `requirements.txt` dùng `>=` không khoá phiên bản. Thêm CI (pytest, ruff, `tsc`, lint, vitest, build Docker), khoá phụ thuộc (uv hoặc pip-tools), và một job đêm chạy `run_rag_eval --min-hit5 … --min-mrr …` làm cổng chất lượng.
- **Quan sát:** Langfuse chỉ là tuỳ chọn. Thêm metric Prometheus/OpenTelemetry theo từng bước (planner, truy xuất, rerank, sinh, ghi bộ nhớ) và ID yêu cầu xuyên suốt.
- **Vệ sinh kho:** thư mục lạ `%SystemDrive%` ở gốc, `model_cache/`, `.agents/` (6,6 MB), file `.docx` báo cáo và 17 MB tài liệu mẫu nằm trong git (nên dùng Git LFS hoặc tải riêng), thư mục `legacy/`.
- **Test backend chủ yếu dùng mock.** Thêm test hợp đồng cho gateway (`TestClient`), test tích hợp với Postgres/Redis thật (testcontainers) và một kịch bản tải (Locust).

## 6. Lộ trình đề xuất

1. **Tuần 1–2 (chặn rủi ro):** xác thực + gắn phiên với user, đóng cổng 8000, rate limit, trần upload, khoá phụ thuộc, CI cơ bản, `/ready`, chặn secret mặc định, xoá thư viện thừa, **sửa lỗi bộ nhớ #1 và #2 (mục 3.3, bước 1–2)**.
2. **Tuần 3–6 (độ tin cậy):** đưa trạng thái ra Redis/Postgres (phê duyệt, checkpoint, **bộ nhớ dài hạn bền vững theo user**); role Postgres chỉ đọc + RLS thật; API hội thoại phía server; tách `core.py`, `main.py`, `ChatInterface.tsx`; bộ đếm quan sát.
3. **Sau đó (chất lượng):** stream token câu trả lời, i18n và a11y, Alembic, kiểm thử tải, nâng Next/React.

Nếu chỉ chọn một việc để làm trước, đó là **xác thực + gắn danh tính vào phiên, HITL, tenant và bộ nhớ**, vì các cơ chế bảo mật và cá nhân hoá hiện có chỉ có ý nghĩa khi có danh tính thật.
