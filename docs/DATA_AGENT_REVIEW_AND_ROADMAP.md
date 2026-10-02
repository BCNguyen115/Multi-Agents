# Data Agent: Review sâu và lộ trình

Phạm vi: `src/agents/data_agent/` (agent.py, profiler.py, sandbox.py, prompt_templates.py), `src/orchestrator/verifier.py`, `src/shared/csv_sanitizer.py`, và điểm nhận file ở `src/gateway/main.py`.
Phương pháp: đọc toàn bộ luồng chính của `agent.py` (khoảng 3.600 dòng) và chạy thử các nghi vấn quan trọng bằng Python. Mục nào đã chạy thật được đánh dấu **[đã kiểm chứng]**; mục còn lại là kết luận từ đọc code.

---

## Trạng thái triển khai (cập nhật sau khi thực hiện lộ trình)

Toàn bộ Phase 1–4 đã được cài đặt và kiểm thử; `agent.py` cũ (≈3.600 dòng) và `prompt_templates.py` đã được thay bằng các module nhỏ (`ingest`, `profiler`, `insights`, `charts`, `story`, `qa`, `sandbox`, `verifier`).

| Hạng mục | Trạng thái | Cách kiểm chứng |
|---|---|---|
| Đọc đa định dạng (CSV/TSV/Excel/Parquet/JSON), encoding, tiền tệ/phần trăm/ngày dạng chữ | Xong | `tests/test_ingest_and_profiler.py`, 18 bộ dữ liệu "xấu" trong `tests/test_adversarial_datasets.py`, tải thật qua API và trình duyệt |
| Profiler theo giá trị/thống kê; chính sách cộng (sum) vs trung bình (avg) | Xong | test profiler; test metamorphic đổi tên/xáo trộn cột-hàng không đổi số liệu |
| Insight engine (xu hướng, thay đổi kỳ, đóng góp, tỷ trọng, xếp hạng, khác biệt nhóm, tương quan, phân phối, bất thường) | Xong | `tests/test_insights.py` (dữ liệu có cài sẵn quy luật) |
| Chart compiler duy nhất + 10 loại biểu đồ + KPI có delta | Xong | `tests/test_charts.py`, `frontend/tests/unit/chartOption.test.ts` |
| Story sinh từ fact (đúng theo cấu trúc); LLM chỉ được diễn đạt lại nếu giữ nguyên số **và tên nhóm/cột** | Xong | `tests/test_story.py`, phát hiện và chặn một ca LLM đổi nghĩa khi chạy thật |
| Verifier tính lại biểu đồ/KPI/insight từ chính tệp tải lên | Xong | `tests/test_verifier.py`, `tests/test_agent_e2e.py` |
| Hỏi–đáp text-to-analysis trong sandbox cách ly | Xong | `tests/test_sandbox_security.py` (33 kiểu thoát sandbox bị chặn), `tests/test_agent_e2e.py` |
| Lọc chéo (cross-filter) tính lại + kiểm chứng phía server | Xong (mới, ngoài lộ trình gốc) | `POST /api/analyze/filter`, test e2e, thử thật trên trình duyệt |
| Frontend v2 (câu chuyện, KPI delta, slicer, xuất PDF/PPTX/CSV) | Xong | `npm run build`, `npm run lint`, `tsc`, vitest, Playwright thao tác thật |

**Chưa làm / giới hạn đã biết**: nạp bảng lớn bằng DuckDB phía server (hiện lấy mẫu ngẫu nhiên có thông báo khi vượt `DATA_MAX_ROWS`); bản đồ địa lý, box/funnel; lưu toàn bộ CSV trong Redis là giải pháp tạm; rlimit của sandbox chưa có trên Windows (chỉ timeout + môi trường sạch); tên cột chỉ ảnh hưởng qua từ vựng tiếng Anh/Việt để quyết định "cộng được hay trung bình" (cột như `Umsatz` không có tín hiệu này sẽ được lấy trung bình an toàn); `.xls` cũ chưa được hỗ trợ; các spec Playwright e2e cũ (`frontend/tests/e2e`) chưa được cập nhật cho giao diện mới.

---

## 0. Đính chính các báo cáo trước

| Điều đã nói trước đó | Thực tế |
|---|---|
| "Quét lại `order_date`, `customer_id`, ... không còn kết quả" | Đúng với các chuỗi đó, nhưng lần quét **bỏ sót `order_month`**: chuỗi này vẫn được gán cứng ở khoảng 20 chỗ trong `agent.py`, trong whitelist của `verifier.py:38`, 4 chỗ trong `DynamicDashboard.tsx` và 7 assertion trong test. Nó còn được đặt tên sai khi gom theo ngày hoặc năm. |
| "`verifier.py` không cần sửa, không chứa tên cột cứng" | Sai. Verifier vẫn suy luận theo tên cột (mục B4, B5 bên dưới). |
| "Layer 1 hoàn tất" | `profiler.py` sạch, nhưng `agent.py` vẫn còn nhiều luật theo tên cột và một bộ phân loại thứ hai chạy song song (mục B3). |

---

## 1. Kết luận tóm tắt

Data agent hiện là **bộ dựng dashboard 4 mẫu cố định**, không phải một data analyst. Có ba khoảng trống lớn so với mục tiêu "xử lý mọi dataset, get insight, data storytelling":

1. **Không có insight engine.** Không tính xu hướng, đóng góp, bất thường, tương quan hay so sánh nhóm. Phần "Diễn biến / Nguyên nhân / Khuyến nghị" do LLM viết chỉ dựa trên tổng, trung bình, max, min và 6 điểm dữ liệu. "Nguyên nhân" và "Khuyến nghị" không có bằng chứng nào, và bản dự phòng (`agent.py:3085-3101`) in sẵn câu nguyên nhân chung chung như thể là sự thật.
2. **Không có đường trả lời câu hỏi phân tích.** Sandbox chạy code (`sandbox.py`) **không được gọi ở đâu cả** (`execute_sandbox_code` ở `agent.py:1612` và `_validate_code_safety` ở `agent.py:3597` đều là mã chết). Câu hỏi không phải yêu cầu dashboard chỉ nhận về thống kê `describe()` cộng LLM, nên số liệu trong câu trả lời có thể bịa.
3. **Nạp và suy luận dữ liệu chưa đủ tổng quát.** Chỉ đọc CSV; CSV dùng dấu `;` bị đọc thành 1 cột; tên cột phi Latin bị xóa sạch; trung bình bị tính sai khi có ô trống. Vài lỗi trong số này làm sai số liệu **mà không báo lỗi**.

Hướng đi đề xuất ở mục 4: đổi từ "LLM dựng biểu đồ rồi sửa lại bằng luật" sang **Profile → Insight → Plan → Compile → Verify → Narrate**, trong đó mọi con số do code tính và LLM chỉ diễn đạt.

---

## 2. Kiến trúc hiện tại

```
CSV ─► safe_read_csv ─► classify_columns_advanced (+ profiler.py, hai bộ phân loại chồng nhau)
        │
        ├─ không phải yêu cầu dashboard ─► describe() + 1 LLM call ─► văn bản
        │
        └─ dashboard ─► parse intent (LLM) ─► vòng lặp tối đa 3 lần:
              layout LLM ─► build_universal_archetype_charts (4 mẫu, xác định)
                         ─► validate_and_correct_chart_specs (vá bằng regex/luật)
                         ─► storyteller LLM ─► 2 evaluator (chỉ kiểm cấu trúc)
           ─► nhúng toàn bộ bảng (tới 10.000 dòng) x5 bản vào JSON ─► frontend
```

Nhận xét kiến trúc: kết quả của "layout LLM" gần như bị bỏ qua vì biểu đồ do bộ dựng xác định tạo ra; hai LLM call trong mỗi vòng lặp (layout, chart intent) tốn chi phí mà đóng góp thấp.

---

## 3. Phát hiện chi tiết

Mức độ: **Cao** = sai số liệu hoặc mất bảo mật; **Trung** = sai với một lớp dataset; **Thấp** = nợ kỹ thuật.

### A. Sai số liệu (Cao)

| # | Vấn đề | Vị trí | Bằng chứng |
|---|---|---|---|
| A1 | Ô trống bị đổi thành 0 **trước** khi lấy trung bình/tổng nhóm, kéo trung bình xuống. Ví dụ `[10, NaN, 30]`: trung bình đúng 20, hệ thống ra 13,33. | `agent.py:551, 599, 660, 732, 2337` | **[đã kiểm chứng]** |
| A2 | Mọi biểu đồ mặc định dùng SUM cho mọi measure. Cộng giá bán, điểm đánh giá, tuổi, nhiệt độ là vô nghĩa. Không có khái niệm measure cộng được (tiền, số lượng) so với không cộng được (đơn giá, rating). KPI "TỔNG X" cũng chịu lỗi này. | `agent.py:552, 601, 662, 2594` | Đọc code |
| A3 | Biểu đồ tùy chỉnh luôn ghi `aggregation: "SUM"` dù dữ liệu tính bằng mean/median/count theo ý người dùng. Nhãn nói SUM, số liệu là trung bình. | `agent.py:2481` vs `2339-2346` | Đọc code |
| A4 | `_refine_dashboard_spec` gán `chart["data"] = agg_data.get("bar_chart_data", [])` nhưng hàm được gọi không trả khóa đó, nên biểu đồ "được sửa" thành **mảng rỗng**. | `agent.py:3384` | Đọc code |
| A5 | Tiêu đề luôn ghi "Theo Tháng" cho biểu đồ thời gian kể cả khi gom theo ngày hoặc năm; cột gom tên `order_month` chứa cả `%Y-%m-%d` và `%Y`. | `agent.py:2397`, `540-546` | Đọc code |
| A6 | Sau khi hết lượt thử vẫn bị ép `verified = True`, nên `pev_trace` báo "đã kiểm duyệt" cho dashboard chưa đạt. | `agent.py:1885-1892` | Đọc code |
| A7 | Chỉ đọc 50.000 dòng đầu (`iloc[:max_rows]`) mà không báo trong dashboard. Tổng và KPI của file lớn sai, và với chuỗi thời gian sắp theo ngày, phần cuối bị mất. | `agent.py:131-138` | Đọc code |

### B. Không tổng quát hóa được (Trung đến Cao)

| # | Vấn đề | Vị trí | Bằng chứng |
|---|---|---|---|
| B1 | File CSV dùng `;` hoặc tab bị đọc thành **một cột**. Chỉ khi mọi encoding đều lỗi mới thử dò dấu phân cách. Kết quả còn bị đổi tên thành `abc`. | `agent.py:106-125` | **[đã kiểm chứng]** |
| B2 | Tên cột phi Latin (Nhật, Trung, Nga, Ả Rập, Thái...) bị xóa sạch thành `col_0`, `col_1`. Mất toàn bộ ngữ nghĩa. Ngoài ra không giữ nhãn gốc để hiển thị. | `csv_sanitizer.py:95` | **[đã kiểm chứng]** |
| B3 | Có **hai bộ phân loại cột chồng nhau** (`profiler.py` theo vai trò, `classify_columns_advanced` theo luật riêng) với ngưỡng và kết quả có thể khác nhau. | `agent.py:242-458` | Đọc code |
| B4 | Cột bị coi là ID theo chuỗi con: `smartphone_price` (chứa `phone`), `keyword_count` (chứa `key`), `paid` (kết thúc `id`), `zipcode` bị verifier coi là ID và cấm SUM/AVG. Trong khi `profiler.py` lại không nhận ra `customer_uuid` và `zipcode`. Ba nơi có ba regex ID khác nhau (profiler, verifier, frontend). | `verifier.py:18`, `profiler.py:33`, `DynamicDashboard.tsx:138` | **[đã kiểm chứng]** |
| B5 | Verifier coi cột là ngày nếu tên chứa `day`, `time`, `month`, `year`. Các cột phân loại như `day_of_week`, `holiday_flag`, `month_name` bị cấm dùng làm bar ranking. | `verifier.py:134` | Đọc code |
| B6 | Luật `["year","nam","rank","stt"]` loại cột số ra khỏi measure. `nam` xuất hiện trong `dy`**`nam`**`ic_price`, nên measure này biến mất. | `agent.py:309-311` | **[đã kiểm chứng]** |
| B7 | Nhận ratio theo tên (`rate`, `share`, `margin`) và mọi cột số nằm trong [0,1] bị loại khỏi measure, gồm cả điểm chuẩn hóa hoặc xác suất là đối tượng phân tích chính. Chọn archetype "vận hành" nếu có cột tên chứa `status`, `step`, `stage`. | `agent.py:163, 290-295, 401-404` | Đọc code |
| B8 | Chọn measure chính theo tổng độ lớn, nên "population" hay "price" thắng theo tỷ lệ đơn vị, không theo ý nghĩa kinh doanh hay câu hỏi người dùng. | `agent.py:180-187, 203-211` | Đọc code |
| B9 | Không hỗ trợ Excel, Parquet, JSON, nhiều sheet dù metadata agent mô tả "CSV/Excel". Gateway chỉ đọc byte và coi là CSV. | `agent.py:1625`, `main.py:788-793` | Đọc code |
| B10 | Toàn bộ chuỗi giao diện tiếng Việt viết cứng (tiêu đề, "Khác", "Số Lượng Giao Dịch"...). Dashboard không theo ngôn ngữ người dùng. Từ "giao dịch" ngầm định dataset là giao dịch. | rải rác trong `agent.py` | Đọc code |
| B11 | Chỉ có 4 loại biểu đồ (area/line, donut, bar xếp hạng, bar so sánh). Không có scatter, histogram/box, heatmap, treemap, waterfall, funnel, bản đồ. Không có cách khám phá quan hệ giữa hai measure. | `agent.py:461-1008` | Đọc code |
| B12 | Chỉ có một cột thời gian chính, grain chỉ ngày/tháng/năm. `classify_columns_advanced` có tính quý nhưng bộ dựng chart bỏ qua. Không so sánh kỳ với kỳ. | `agent.py:363-368`, `538-547` | Đọc code |

### C. Storytelling và insight (Cao so với mục tiêu)

| # | Vấn đề | Vị trí |
|---|---|---|
| C1 | Không có bước tính insight. LLM chỉ nhận `total_sum`, `average_val`, `max_val`, `min_val` và 6 điểm, rồi được yêu cầu viết "Nguyên nhân" và "Khuyến nghị". Đây là điều kiện sinh nội dung suy đoán. | `agent.py:3036-3069` |
| C2 | Bản dự phòng (không cần LLM) khẳng định "biến động phản ánh sự tập trung ở các giai đoạn cao điểm" như một sự thật, không dựa trên dữ liệu nào. | `agent.py:3090-3092` |
| C3 | Bộ kiểm tra story chỉ tìm ba tiêu đề "Diễn biến / Nguyên nhân / Khuyến nghị" trong văn bản. **Không đối chiếu con số** nào với dữ liệu. Prompt yêu cầu "mọi con số trích từ JSON" nhưng không có cơ chế thực thi. | `agent.py:3290-3308` |
| C4 | Chỉ một đoạn nhận định chung cho cả dashboard. Không có nhận định theo từng biểu đồ, không đánh dấu điểm đỉnh/đáy hay bất thường trên biểu đồ. | toàn bộ pipeline |
| C5 | KPI chỉ là tổng, trung bình, số bản ghi, số thực thể. Không có thay đổi so với kỳ trước, không có tỷ trọng top-N, không có cảnh báo chất lượng dữ liệu. | `agent.py:2575-2660` |
| C6 | "Top N đóng góp lớn nhất" trong tiêu đề nhưng không tính tỷ trọng đóng góp nào. | `agent.py:685` |

### D. Bảo mật và độ bền (Cao)

| # | Vấn đề | Vị trí |
|---|---|---|
| D1 | **Prompt injection gián tiếp.** Tên cột và giá trị ô của file người dùng tải lên được ghép thẳng vào prompt (`Danh sách các cột THỰC TẾ`, `top 3 values`). Gateway chỉ quét câu hỏi, không quét nội dung file. Tên cột đã qua sanitizer, nhưng giá trị ô thì không. | `agent.py:2078-2083, 2780`, `profiler.py:244-271` |
| D2 | Sandbox lọc mã bằng regex danh sách đen (`os.system`, `eval(`...). Danh sách đen dễ bị vượt qua (`getattr`, `__class__`, `importlib`). Hiện chưa gọi tới nên chưa gây hại, nhưng phải thay bằng AST allow-list trước khi bật đường Q&A. | `agent.py:57-73` |
| D3 | Toàn bộ nội dung file (tối đa 10 MB) lưu vào Redis theo session dưới dạng chuỗi và parse lại mỗi yêu cầu. | `agent.py:1702-1716` |
| D4 | Dữ liệu bảng bị nhân **5 bản** trong cùng một JSON (`table.rows`, `raw_data`, `rawData`, `rawRows`, `rows`) và tới 10.000 dòng mỗi bản, rồi đi qua orchestrator (`json.loads` rồi `json.dumps` thêm lần nữa) và SSE. Với file lớn payload lên tới hàng chục MB. | `agent.py:3327-3334`, `3452-3458` |
| D5 | Mỗi vòng lặp chất lượng chạy lại **cả** layout LLM, chart, storyteller và hai evaluator, dù lỗi chỉ ở một phần. Tối đa 3 vòng thành 9+ LLM call cho một dashboard. | `agent.py:1807-1882` |
| D6 | `_evaluate_chart_data_quality` vừa "kiểm tra" vừa sửa (mutate) spec, nên không thể coi là bước kiểm định độc lập. | `agent.py:3192-3288` |

### E. Nợ kỹ thuật (Thấp đến Trung)

- `validate_and_correct_chart_specs` (khoảng 560 dòng) vá spec bằng thay chuỗi tiêu đề tiếng Việt và ghi đè dimension theo tiêu đề; logic "tính lại dữ liệu" lặp 5 lần (`agent.py:1011-1575`). Đây là triệu chứng của việc để LLM sinh spec rồi sửa sau.
- Đoạn chọn dimension chưa dùng (`str(c).lower() not in used_dims and ... not in id_cols and c not in temporal_cols`) lặp khoảng 20 lần trong bộ dựng archetype.
- Màu hex viết cứng trong backend (`#6366f1`, `#EF4444`) chảy sang frontend, ngược với việc dùng design token.
- Cùng một nghiệp vụ tổng hợp được cài ở **3 nơi** (Python backend, JS trong `DynamicDashboard.tsx`, và `buildUniversalQuery` cho DuckDB), nên số liệu có thể lệch giữa các nơi.
- `has_data_intent` chứa từ khóa miền nghiệp vụ ("bán hàng", "doanh thu") (`agent.py:1644-1651`).
- `_is_dashboard_request` có ba bản sao (orchestrator, agent, fallback) với danh sách từ khóa khác nhau.

---

## 4. Hướng đi đề xuất

### 4.1 Nguyên tắc

1. **Code tính, LLM diễn đạt.** Mọi con số trên dashboard và trong lời kể phải sinh từ một bảng "fact" do code tính và có thể kiểm chứng.
2. **Một nguồn sự thật cho biểu đồ.** Một `ChartSpec` có kiểu (pydantic), một trình biên dịch spec ra dữ liệu. Không vá spec bằng regex.
3. **Ngữ nghĩa từ giá trị và thống kê, không từ tên cột.** Kiểm chứng bằng test "đổi tên cột" (mục 4.10).
4. **Nói rõ điều chưa chắc.** Nguyên nhân chỉ được nêu khi có bằng chứng; nếu không thì gắn nhãn giả thuyết.

### 4.2 Kiến trúc đích

```
Ingest ─► Profile v2 ─► Insight Engine ─► Dashboard Planner ─► Spec Compiler ─► Verify ─► Narrate
 (đa định dạng)  (vai trò+chính sách   (facts có điểm số)   (theo câu hỏi        (SQL/pandas)   (đối chiếu   (LLM chỉ viết
                  cộng gộp+chất lượng)                        phân tích)                         số liệu)     từ facts)
                                                   └────────────► Q&A text-to-analysis (sandbox AST) ─┘
```

### 4.3 Lớp 0: Nạp dữ liệu (`ingest/`)

- Dùng **DuckDB** (đã có ở frontend, thêm phía server) để đọc CSV/TSV/Excel/Parquet/JSON. DuckDB tự dò dấu phân cách và kiểu, và cho phép tính trên file lớn mà không nạp hết vào pandas.
- Dò encoding và dấu phân cách trước khi đọc; báo lại cho người dùng ("Đã đọc dạng `;`, UTF-8, 12 cột").
- **Tách tên hiển thị và mã cột**: giữ nguyên nhãn gốc (kể cả CJK) để hiển thị, dùng mã an toàn cho truy vấn.
- Suy kiểu từ giá trị: tiền tệ (`$1,200`, `1.200,50 €`), phần trăm (`12%`), dấu phân cách nghìn, boolean, ngày nhiều định dạng.
- File lớn: lấy mẫu **ngẫu nhiên/phân tầng** hoặc đẩy tính toán xuống DuckDB; luôn ghi vào dashboard "đã dùng X% dòng".
- Không lưu cả file vào Redis; lưu tham chiếu tới file đã parse (Parquet tạm) và cache DataFrame theo session.

### 4.4 Lớp 1: Profiler v2 (mở rộng `profiler.py`, xóa `classify_columns_advanced`)

Một bộ phân loại duy nhất, chỉ dùng giá trị và thống kê:

- Vai trò: identifier, temporal, measure, categorical (thấp/cao), **boolean/flag, ordinal, text tự do, địa lý (lat/lon, mã quốc gia), phần trăm/tỷ lệ**.
- **Chính sách cộng gộp cho từng measure**: `additive` (SUM hợp lệ), `intensive` (dùng AVG/MEDIAN: giá, điểm, tuổi, nhiệt độ), `ratio` (tính lại từ tử/mẫu, không cộng). Suy luận từ phân phối: số nguyên không âm, chuẩn hóa, phạm vi hẹp, nhận diện điểm Likert...
- Grain của bảng ("một dòng là gì"), khóa tự nhiên, quan hệ phân cấp (quốc gia → thành phố) bằng phụ thuộc hàm.
- Chất lượng: tỷ lệ thiếu, trùng lặp, ngoại lai, độ lệch; xuất thành danh sách cảnh báo có thể hiển thị.
- Sau bước này, `verifier.py` và `agent.py` chỉ **đọc** profile, không suy luận theo tên nữa (giải quyết B3–B8, A1–A2).

### 4.5 Lớp 2: Insight Engine (module mới, cốt lõi cho "get insight")

Mỗi bộ sinh cho ra các `Insight` có cấu trúc: `{id, type, numbers, evidence_spec, importance, confidence, caveats}`, rồi xếp hạng theo độ quan trọng × độ bất ngờ.

| Loại | Ví dụ nội dung | Cách tính (thư viện: pandas, scipy, scikit-learn) |
|---|---|---|
| Xu hướng | Tăng/giảm %, CAGR, điểm gãy | hồi quy, so sánh kỳ, change-point |
| So sánh kỳ | MoM/YoY, kỳ này so với cùng kỳ | resample + shift |
| **Nguyên nhân thay đổi** | Nhóm nào đóng góp bao nhiêu điểm % vào mức tăng/giảm | contribution analysis giữa hai kỳ |
| Cơ cấu | Top-N chiếm bao nhiêu %, mức tập trung (Pareto, HHI) | share, cumulative |
| Xếp hạng | Chênh lệch giữa hạng 1 và trung bình | chuẩn hóa |
| So sánh nhóm | Nhóm A khác nhóm B có ý nghĩa không | effect size + kiểm định (Mann-Whitney/ANOVA) |
| Tương quan | Cặp measure liên hệ mạnh nhất | Spearman, lọc đa cộng tuyến |
| Phân phối | Lệch, đuôi dài, ngoại lai | IQR/MAD, skew |
| Bất thường theo thời gian | Ngày/tháng lạ | STL hoặc z-score trượt |
| Chất lượng dữ liệu | Cột thiếu >30%, trùng, đơn vị lẫn lộn | từ profile |

Đây là phần thay thế trực tiếp cho C1–C6 và là nền tảng cho câu chuyện dữ liệu.

### 4.6 Lớp 3–4: Planner và Spec Compiler

- **Planner chọn biểu đồ theo câu hỏi phân tích** thay vì 4 archetype: *Chuyện gì xảy ra?* (xu hướng + KPI có delta), *Ở đâu/Ai?* (xếp hạng, treemap, bản đồ), *Vì sao?* (waterfall đóng góp, phân rã), *Có liên quan không?* (scatter, heatmap tương quan), *Phân phối thế nào?* (histogram, box), *Bất thường?* (đường có đánh dấu điểm lạ).
- Chọn biểu đồ bằng bảng luật kiểu `(vai trò cột) → biểu đồ ứng viên`, chấm điểm theo **insight nào biểu đồ đó chứng minh** và tránh trùng lặp về thông tin (không chỉ trùng cột).
- **`ChartSpec` (pydantic)**: `type, dimension, measure, aggregation, grain, filter, sort, limit, format{unit,currency,percent}, label{i18n}`. Một hàm `compile(spec, dataset) → data` duy nhất, dùng chung cho backend và (qua `buildUniversalQuery`) cho DuckDB WASM ở frontend. Có test **tương đương** giữa hai đầu.
- LLM tùy chọn chỉ để chọn/đặt tên trong tập ứng viên hợp lệ, không sinh dữ liệu. Bỏ `validate_and_correct_chart_specs`.
- Bỏ việc nhân bản dữ liệu bảng: gửi một lần, phân trang hoặc tải riêng (D4).

### 4.7 Lớp 5: Storytelling có kiểm chứng

- **Cấu trúc câu chuyện:** tiêu đề chính (câu trả lời cho "điều gì quan trọng nhất"), 3–5 phát hiện xếp theo độ quan trọng, "ý nghĩa/hành động", lưu ý dữ liệu, câu hỏi gợi ý tiếp theo.
- LLM nhận **bảng facts** và phải trích **ID fact** cho mỗi câu. "Nguyên nhân" chỉ dùng số từ contribution analysis; nếu không có bằng chứng thì gắn "giả thuyết cần kiểm tra".
- **Bộ kiểm chứng số liệu:** trích mọi con số trong văn bản, đối chiếu với bảng facts (dung sai làm tròn); sai thì tái sinh hoặc loại câu đó. Đây là bước biến "zero-hallucination" thành cơ chế thật thay vì lời nhắc trong prompt.
- Chú thích theo từng biểu đồ: một câu nhận định + đánh dấu điểm đỉnh/đáy/bất thường trên biểu đồ (ECharts `markPoint`/`markArea`).
- Ngôn ngữ đầu ra theo ngôn ngữ người dùng; tách chuỗi giao diện ra bảng i18n.

### 4.8 Lớp 6: Hỏi đáp phân tích (text-to-analysis)

- LLM viết truy vấn (SQL DuckDB hoặc pandas) trên **schema và profile**, không phải trên dữ liệu thô.
- Thực thi trong sandbox đã có nhưng **nâng cấp**: AST allow-list thay regex, giới hạn thời gian/bộ nhớ, tách tiến trình hoặc dùng container `python-sandbox` đã có trong compose (đang không có mạng).
- Kết quả trả về bảng số liệu và biểu đồ tự động, rồi kể chuyện từ chính bảng đó. Nhờ vậy hỏi "top 5 khách theo X" hay "A có tương quan với B không" đều có số liệu thật.
- Giữ ngữ cảnh follow-up bằng DataFrame/Parquet cache theo session.

### 4.9 Bảo mật đi kèm

- Bọc mọi nội dung lấy từ file (tên cột, giá trị ô) trong khối dữ liệu được đánh dấu, chặn các mẫu chỉ thị, và quét bằng cùng bộ quét prompt-injection của gateway.
- Giới hạn số cột và độ dài tên/giá trị đưa vào prompt.

### 4.10 Đánh giá (bắt buộc để chứng minh "mọi dataset")

- **Bộ 15–20 dataset đối nghịch**: bán lẻ, âm nhạc, y tế, hàng không, nhân sự, tài chính, cảm biến IoT, khảo sát Likert, địa lý, nhiều văn bản, rất rộng (200 cột), rất nhỏ (20 dòng), tên cột phi Latin, CSV dấu `;`, Excel nhiều sheet.
- **Metamorphic test** (chỉ cần dữ liệu tổng hợp, chạy được ngay trong pytest): đổi tên cột ngẫu nhiên, đảo thứ tự cột, đổi ngôn ngữ tên cột → dashboard và insight phải **tương đương** (cùng loại biểu đồ, cùng con số). Đây là cách kiểm tra "không hardcode" bền vững hơn grep chuỗi.
- Chỉ số: schema hợp lệ, % câu trong story khớp fact, độ phủ insight so với danh sách nhãn tay, độ trễ, chi phí LLM. Đưa vào `scripts/run_offline_eval.py` làm cổng CI.

---

## 5. Lộ trình thực hiện

| Giai đoạn | Nội dung | Ước lượng | Rủi ro / ghi chú |
|---|---|---|---|
| **0. Sửa lỗi ngay** | A1, A3, A4, A6; B1 (dò dấu phân cách); B2 (giữ nhãn gốc, không xóa ký tự Unicode); B4 và B5 (dùng profile thay regex trong verifier); B6; đổi `order_month` thành tên trung tính theo grain; xóa `verified = True` ép buộc | 2–3 ngày | Cần cập nhật 7 assertion test và frontend (4 chỗ). Sửa A1 làm thay đổi số liệu KPI, cần thông báo |
| **1. Nền tảng dữ liệu** | Ingest bằng DuckDB (đa định dạng), Profiler v2 (vai trò, chính sách cộng gộp, chất lượng), xóa `classify_columns_advanced`, `ChartSpec` + trình biên dịch, bỏ nhân bản payload | 1–1,5 tuần | Thay đổi lõi; cần bộ test metamorphic trước khi đổi |
| **2. Insight Engine** | Các bộ sinh xu hướng, so sánh kỳ, cơ cấu, contribution, tương quan, bất thường, chất lượng; xếp hạng insight | 1–1,5 tuần | Chọn ngưỡng ý nghĩa thống kê hợp lý để tránh nhiễu |
| **3. Planner + Storytelling** | Planner theo câu hỏi phân tích; thêm scatter/histogram/heatmap/treemap/waterfall; story theo facts; bộ kiểm chứng số liệu; chú thích từng biểu đồ; i18n | 1–1,5 tuần | Cần mở rộng frontend cho loại biểu đồ mới |
| **4. Q&A phân tích** | text-to-analysis, sandbox AST allow-list, bảo mật prompt | 1 tuần | Bảo mật là điểm khó nhất, cần review riêng |
| **5. Đánh giá & CI** | Bộ dataset đối nghịch, eval gate, đo chi phí/độ trễ | 3–5 ngày | Nên làm song song từ giai đoạn 1 |

Thứ tự khuyến nghị: **0 → (5 song song) → 1 → 2 → 3 → 4**. Giai đoạn 0 và 2 đem lại giá trị lớn nhất so với công sức: 0 sửa số sai, 2 tạo ra insight thật.

## 6. Đối chiếu yêu cầu "get insight" và "data storytelling"

| Yêu cầu | Hiện tại | Sau lộ trình |
|---|---|---|
| Nêu được điều gì đang xảy ra | Có KPI tổng/trung bình | KPI có delta theo kỳ, xu hướng có % và điểm gãy |
| Chỉ ra ở đâu/ai đóng góp | Bar top-N, không có tỷ trọng | Cơ cấu, Pareto, HHI, contribution |
| Giải thích vì sao | LLM suy đoán, không bằng chứng | Phân rã đóng góp; giả thuyết được gắn nhãn |
| Phát hiện bất thường/rủi ro | Không có | Bất thường theo thời gian, ngoại lai, cảnh báo chất lượng |
| Tìm quan hệ giữa các biến | Không có | Tương quan, scatter, heatmap |
| Kể chuyện có cấu trúc | 3 dòng chung cho cả dashboard | Tiêu đề chính, phát hiện xếp hạng, ý nghĩa, lưu ý, câu hỏi tiếp theo, chú thích từng biểu đồ |
| Số liệu tin cậy | Không kiểm chứng số trong lời kể | Đối chiếu mọi số với bảng facts |
| Trả lời câu hỏi tự do | Chỉ `describe()` + LLM | Text-to-analysis chạy thật, có số liệu |
| Mọi dataset | Chỉ CSV `,`, tên cột Latin | Đa định dạng, Unicode, kiểm bằng metamorphic test |

## 7. Rủi ro và điều chưa kiểm chứng

- Các mục đánh dấu "Đọc code" chưa chạy thật; nên viết test tái hiện trước khi sửa (A2–A7, B3, B5, B7–B12, C, D).
- Ước lượng thời gian giả định một người, chưa tính review và điều chỉnh frontend.
- Chưa đo chi phí LLM thực tế của vòng lặp chất lượng (D5); con số "9+ call" là suy ra từ code.
- Chưa xem `sandbox.py` chi tiết và `db_agent` (ngoài phạm vi báo cáo này).
