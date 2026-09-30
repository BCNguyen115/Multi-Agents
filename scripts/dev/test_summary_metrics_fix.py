import sys
import json
import asyncio
import re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def extract_data_metrics(text: str):
    rows = None
    cols = None
    if text:
        row_match = re.search(r"(?:Số lượng dòng|Tổng số dòng|Số bản ghi)\D*?([0-9,.]+)", text, re.IGNORECASE)
        if not row_match:
            row_match = re.search(r"([0-9,.]+)\s*(?:dòng|bản ghi)", text, re.IGNORECASE)
        if row_match and row_match.group(1):
            val = re.sub(r"[^0-9]", "", row_match.group(1))
            if val:
                rows = int(val)

        col_match = re.search(r"(?:Số lượng cột|Tổng số cột|Số trường|Số thuộc tính)\D*?([0-9,.]+)", text, re.IGNORECASE)
        if not col_match:
            col_match = re.search(r"([0-9,.]+)\s*(?:cột|trường|thuộc tính)", text, re.IGNORECASE)
        if col_match and col_match.group(1):
            val = re.sub(r"[^0-9]", "", col_match.group(1))
            if val:
                cols = int(val)

    return {"rows": rows, "cols": cols}

def test_regex():
    testcases = [
        ("- **Số lượng dòng:** 500\n- **Số lượng cột:** 14", 500, 14),
        ("Số lượng dòng: 500\nSố lượng cột: 14", 500, 14),
        ("Tập dữ liệu gồm 500 dòng và 14 cột.", 500, 14),
        ("| **Tổng số dòng (Rows)** | `5,000` |\n| **Tổng số cột (Columns)** | `27` |", 5000, 27),
    ]

    for text, exp_rows, exp_cols in testcases:
        res = extract_data_metrics(text)
        print(f"Extracted: {res}")
        assert res["rows"] == exp_rows, f"Expected rows {exp_rows}, got {res['rows']}"
        assert res["cols"] == exp_cols, f"Expected cols {exp_cols}, got {res['cols']}"

    print("\n✅ All Regex Extractor Testcases PASSED!")

if __name__ == "__main__":
    test_regex()
