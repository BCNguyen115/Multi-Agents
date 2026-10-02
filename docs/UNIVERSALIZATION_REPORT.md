# Báo cáo Universalization Refactor

Mục tiêu: loại bỏ hardcode tên cột / tên dataset / mã màu tĩnh trong `src/` và `frontend/`, để hệ thống xử lý được bất kỳ dataset nào.

## 1. Kết quả kiểm thử

| Hạng mục | Kết quả |
|---|---|
| `pytest tests/` | **190 passed** (trước khi thêm test mới) |
| `tests/test_universal_profiler.py` (mới) | **4 passed** |
| `npm run build` | Thành công. Còn cảnh báo cũ của duckdb-wasm ("Critical dependency"), không liên quan thay đổi này |
| Quét lại chuỗi `order_date`, `customer_id`, `product_category`, `artist_name`, `total_streams`, `#0d1117`, `#18181b`, `#09090b` trong `src/agents`, `src/orchestrator`, `src/gateway`, `frontend/components`, `frontend/lib` | Không còn kết quả |

**Chưa thực hiện:** chạy trực tiếp 3 CSV thật (e-commerce, Spotify, dataset mới) qua dashboard trên trình duyệt. Thay vào đó có test pytest với 3 dataset tổng hợp (retail / music / medical). Cần chạy thủ công trước khi coi là xong.

## 2. Backend

### `src/agents/data_agent/profiler.py`
- Bộ phân loại vai trò cột (`ROLE_IDENTIFIER`, `ROLE_TEMPORAL`, `ROLE_MEASURE`, `ROLE_LOW/HIGH_CARDINALITY`) đã có từ trước.
- **Xóa** `from loguru import logger` (không dùng và chưa cài, làm toàn bộ test suite lỗi khi import).
- **Thêm** `temporal_columns(df)`: nhận diện cột thời gian theo giá trị (≥90% parse được, nunique ≥ 5), không theo tên.
- **Thêm** `is_monetary_name(col)`: một hàm duy nhất, từ khóa tài chính chung (price, cost, amount, revenue, sales, salary, fee, spend, profit, usd, tien, gia). Đây là gợi ý về đơn vị, không phải vai trò cột.

### `src/agents/data_agent/agent.py`
| Thay đổi | Chi tiết |
|---|---|
| Xóa `SEMANTIC_MEASURE_PRIORITY` | Bảng ưu tiên theo tên cột (revenue, total_streams, ...). `get_measure_semantic_score` giờ chỉ dựa trên độ lớn và phương sai |
| Xóa `get_revenue_series` | Chỉ dùng nội bộ; cùng với `calculated_revenue` không dùng đến |
| 6 danh sách từ khóa tiền tệ | Thay bằng `is_monetary_name()` |
| 2 chỗ kiểm tra tên cột ngày (`"date"`, `"order_date"`, `"created_at"`, ...) trong luồng validate chart | Bỏ điều kiện theo tên, dùng danh sách cột thời gian từ profile |
| `date_keywords` trong intent fallback và bộ dựng chart | Thay bằng `temporal_columns(df)` |

Không thay đổi: các từ khóa trong câu hỏi của người dùng ("xu hướng", "trend", "pie", ...). Đó là ngôn ngữ ý định, không phải tên cột.

### `src/orchestrator/verifier.py`, `prompt_templates.py`
Không cần sửa. Đã dùng `profile_dataframe_for_storytelling` và profile động, không chứa tên cột cứng.

## 3. Frontend

### `frontend/lib/formatters.ts` (viết lại)
- Thêm `formatUniversalMetric(val, {isMonetary, unit})`: định dạng theo độ lớn giá trị (K/M/B/T), tiền tệ và đơn vị lấy từ backend. Bỏ các đơn vị giữ chỗ ("Hàng", "Number", "Đơn vị", ...).
- `formatChartMetric` nhận `{isMonetary, unit}` thay vì tên cột.
- **Xóa** `formatMetricValue` và các regex đoán tiền tệ/phần trăm theo tên cột.

### `frontend/lib/duckdb.ts`
- **Xóa** `queryMonthlyTemporalAggregation` và `queryCategoricalAggregation` (không có nơi gọi; hardcode alias `order_month`).
- **Thêm** `buildUniversalQuery(spec, tableName)` và `queryChart`:
  - Tên cột được bọc `"..."` và escape.
  - `aggregation` do LLM sinh nên đi qua allow-list (SUM/AVG/MIN/MAX/COUNT) để chống SQL injection.
  - Không có measure thì dùng `COUNT(*)`, thay vì `SUM(TRY_CAST(null ...))` như bản mẫu.
  - Chuỗi thời gian thử thêm các định dạng ngày `%Y-%m-%d`, `%m/%d/%Y`, `%d/%m/%Y`.
- **Lưu ý:** dashboard hiện vẫn tổng hợp bằng JavaScript từ dữ liệu thô. `buildUniversalQuery` chưa được nối vào dashboard.

### `frontend/lib/types.ts`
Thêm `dimension_label`, `measure_label`, `limit` vào `ChartItem` (chỉ thêm, không phá tương thích).

### `frontend/components/dashboard/DynamicDashboard.tsx`
- Đổi sang `formatUniversalMetric`; KPI dùng `kpi.type === 'currency'` và `kpi.unit` từ backend.
- Xóa `order_id` / `customer_id` khỏi `isIdColumn` (regex chung đã bao phủ).
- Phụ đề biểu đồ: `dimension_label || dimension`, `measure_label || measure || 'Số bản ghi'`, `aggregation || 'COUNT'`. Bỏ nhãn "Theo Tháng (ASC)" / "TOP" cứng.
- Bảng AG-Grid hiển thị số chính xác (`toLocaleString`), không viết tắt K/M và không đoán tiền tệ theo tên cột. Đây là thay đổi hành vi.
- Đổi 3 comment ví dụ nhắc tên cột dataset cụ thể.

### `frontend/components/dashboard/EChartComponent.tsx`
- Thêm `tk`: đọc CSS variables (`--surface`, `--foreground*`, `--border*`, `--accent-*`) qua `getComputedStyle`, tính lại khi đổi theme.
- Thay toàn bộ màu nền/chữ/viền hex và các biểu thức `isDark ? '#...' : '#...'` trong tooltip, pie, dataZoom bằng token.
- Tooltip truyền `chartSpec.isMonetary` / `chartSpec.unit` cho formatter.
- Giữ nguyên `DARK_PALETTE` / `LIGHT_PALETTE` (màu dữ liệu của series) và bóng đổ `rgba(0,0,0,...)`.

### `frontend/app/globals.css`
| Token / khối | Thay đổi |
|---|---|
| `--foreground-muted` (light) | `#64748b` → `#3d4a5c` (≥7:1 trên surface / raised / overlay, tính tay) |
| `--accent-planner/executor/verifier/error/primary` (light) | Đổi sang mức 800/700 (`#92400e`, `#4338ca`, `#065f46`, `#9f1239`, `#1e40af`) để chữ trắng trên nền accent đạt ≥7:1 |
| `--accent-primary-hover` (light) | `#1e3a8a` |
| AG-Grid | Gộp 4 selector (quartz/alpine, sáng/tối) thành một khối dùng token `--surface`, `--foreground`, `--border`, ... |
| Khối `@media print` | Giữ `#ffffff` (giấy in), có chủ đích |

Tác động: màu accent ở light mode tối hơn rõ rệt (ví dụ Planner từ cam sang nâu).

### `Header.tsx`, `ApprovalCard.tsx`
- `Header.tsx`: `text-slate-700` → `text-foreground-secondary`.
- `ApprovalCard.tsx`: `bg-emerald-600 hover:bg-emerald-500` → `bg-accent-verifier hover:opacity-90`.

## 4. Test mới: `tests/test_universal_profiler.py`
1. Vai trò cột đúng theo giá trị (cột ngày tên `placed_on` vẫn là `ROLE_TEMPORAL`).
2. Cột tên giống ngày nhưng chứa văn bản thì không phải temporal.
3. Prompt profile của dataset A không chứa tên cột của dataset B (3 dataset retail / music / medical).
4. `is_monetary_name` chỉ khớp từ khóa tài chính chung.

## 5. Giới hạn còn lại
- Nhận diện tiền tệ vẫn dựa trên danh sách từ khóa tên cột chung, vì không thể suy ra tiền tệ chỉ từ giá trị số.
- `unit` của KPI do backend đặt bằng tên cột dạng Title Case; với KPI không phải tiền tệ, đơn vị này vẫn được nối vào cuối số (hành vi cũ giữ nguyên).
- Các file trùng lặp ở `src/src/` (chưa được theo dõi bởi git) không được chỉnh sửa và vẫn chứa hardcode cũ.
- Bản `.docx` báo cáo hệ thống không được cập nhật.
- Chưa có unit test cho `buildUniversalQuery` (frontend chưa có test runner ngoài Playwright).

## 6. Danh sách file đã đổi
`src/agents/data_agent/profiler.py`, `src/agents/data_agent/agent.py`, `frontend/lib/formatters.ts`, `frontend/lib/duckdb.ts`, `frontend/lib/types.ts`, `frontend/components/dashboard/DynamicDashboard.tsx`, `frontend/components/dashboard/EChartComponent.tsx`, `frontend/components/Header.tsx`, `frontend/components/ApprovalCard.tsx`, `frontend/app/globals.css`, `tests/test_universal_profiler.py` (mới), `docs/UNIVERSALIZATION_REPORT.md` (file này).
