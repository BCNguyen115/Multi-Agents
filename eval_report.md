# Offline Evaluation Report

- **Timestamp:** `2026-08-13 14:20:21`
- **Mode:** `offline`
- **Total Test Cases:** `10`
- **Quality Gate:** `✅ PASSED`

---

## Metrics Summary

| Metric | Score | Threshold | Status |
|--------|-------|-----------|--------|
| Tool Call Accuracy | `100.0%` | `>= 85%` | `✅` |
| RAG Faithfulness | `86.7%` | `>= 80%` | `✅` |
| Hallucination Rate | `0.0%` | `<= 15%` | `✅` |
| **Composite Score** | **`0.956`** | **`>= 0.85`** | **`✅ RELEASE APPROVED`** |

---

## Detailed Results

| ID | Query | Expected | Predicted | Accuracy | Faithfulness | Score |
|:---|:------|:---------|:----------|:---------|:-------------|:------|
| `eval_001` | Điều khoản bảo mật thông tin trong hợp đồng N... | `rag_agent` | `rag_agent` | `1.0` | `1.0` | `1.0` |
| `eval_002` | Thời hạn hiệu lực của thỏa thuận bảo mật NDA ... | `rag_agent` | `rag_agent` | `1.0` | `1.0` | `1.0` |
| `eval_003` | Hãy phân tích tổng quan doanh thu và số lượng... | `data_agent` | `data_agent` | `1.0` | `0.667` | `0.889` |
| `eval_004` | Vẽ biểu đồ cột thể hiện top 5 sản phẩm bán ch... | `data_agent` | `data_agent` | `1.0` | `1.0` | `1.0` |
| `eval_005` | Các xu hướng phát triển Multi-Agent System và... | `search_agent` | `search_agent` | `1.0` | `1.0` | `1.0` |
| `eval_006` | Tổng hợp tin tức kinh tế tài chính mới nhất h... | `search_agent` | `search_agent` | `1.0` | `1.0` | `1.0` |
| `eval_007` | Truy vấn danh sách 10 người dùng mới nhất từ ... | `db_agent` | `db_agent` | `1.0` | `0.5` | `0.833` |
| `eval_008` | Đếm tổng số bản ghi giao dịch trong cơ sở dữ ... | `db_agent` | `db_agent` | `1.0` | `0.5` | `0.833` |
| `eval_009` | Gửi HTTP GET request kiểm tra health check củ... | `integration_agent` | `integration_agent` | `1.0` | `1.0` | `1.0` |
| `eval_010` | Tạo HTTP POST request đến webhook đối tác với... | `integration_agent` | `integration_agent` | `1.0` | `1.0` | `1.0` |
