import sys
import json
import requests

sys.stdout.reconfigure(encoding="utf-8")

with open("dataset/test_data/ecommerce_sales_analytics_5000.csv", "rb") as f:
    files = {"file": ("ecommerce_sales_analytics_5000.csv", f, "text/csv")}
    data = {
        "query": "Dựng dashboard phân tích doanh thu và cơ cấu kinh doanh từ file bán hàng",
        "session_id": "test_print_charts_clean"
    }
    res = requests.post("http://localhost:3001/api/analyze", files=files, data=data, timeout=120)
    spec = res.json().get("dashboard_spec", {})
    charts = spec.get("charts", [])
    print(f"Total charts: {len(charts)}")
    for i, c in enumerate(charts):
        title = c.get("title")
        subtitle = c.get("subtitle")
        c_type = c.get("type")
        dim = c.get("dimension")
        meas = c.get("measure")
        agg = c.get("aggregation")
        data_preview = c.get("data", [])[:3]
        print(f"\n--- Chart #{i+1} ---")
        print(f"  Title: {title}")
        print(f"  Subtitle: {subtitle}")
        print(f"  Type: {c_type}")
        print(f"  Dimension: {dim}")
        print(f"  Measure: {meas}")
        print(f"  Aggregation: {agg}")
        print(f"  Data Preview: {data_preview}")
