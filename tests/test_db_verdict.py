"""db_agent answers: figures in the prose must come from the returned rows, the row count or the SQL."""
from src.orchestrator.core import Orchestrator

SQL = "SELECT region, SUM(amount) AS total FROM sales WHERE year = 2024 GROUP BY region LIMIT 5"
ROWS = [{"region": "Hà Nội", "total": 1250000}, {"region": "Đà Nẵng", "total": 830000}]


def payload(description: str, rows=ROWS) -> dict:
    answer = f"**Kết quả truy vấn Database ({len(rows)} dòng):**\n\n- **SQL Executed:** `{SQL}`\n- **Mô tả:** {description}\n\n"
    return {"answer": answer, "sql": SQL, "row_count": len(rows), "data": rows}


def verdict(parsed):
    return Orchestrator._db_verdict(parsed, retry_count=0)


def test_numbers_from_the_rows_the_count_and_the_sql_pass():
    assert verdict(payload("Tổng doanh thu năm 2024 của top 5 khu vực: 1,250,000 và 830,000 (2 dòng)."))["is_verified"]


def test_an_invented_figure_fails_with_feedback_and_a_retry():
    result = verdict(payload("Hà Nội đạt 1,250,000, tăng 37% so với năm trước."))
    assert not result["is_verified"] and "37%" in result["verifier_feedback"] and result["retry_count"] == 1


def test_nothing_to_check_without_rows():
    assert verdict(payload("Không có dữ liệu cho 12345.", rows=[]))["is_verified"]
