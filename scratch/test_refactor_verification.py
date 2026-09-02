import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Mock litellm module if not installed
try:
    import litellm
except ImportError:
    mock_litellm = MagicMock()
    sys.modules['litellm'] = mock_litellm

import pandas as pd
from src.agents.data_agent.agent import DataAnalystAgent

async def main():
    # Generate mock CSV with 5000 rows spanning 2022 to 2023
    dates = pd.date_range(start="2022-01-01", periods=5000, freq="h")
    df = pd.DataFrame({
        "order_id": [f"ORD-{i}" for i in range(5000)],
        "order_date": dates.strftime("%Y-%m-%d %H:%M:%S"),
        "revenue": [round(100.0 + (i % 50) * 2.5, 2) for i in range(5000)],
        "category": ["Electronics" if i % 2 == 0 else "Clothing" for i in range(5000)]
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")

    # Mock LLM Client
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = "📈 Diễn biến: Doanh thu hàng tháng phát triển ổn định.\n🔍 Nguyên nhân: Nhu cầu tăng.\n🎯 Khuyến nghị: Duy trì tăng trưởng."
    mock_resp.choices = [MagicMock(message=mock_msg)]
    mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

    agent = DataAnalystAgent(llm_client=mock_llm)

    query = "Tạo biểu đồ đường xu hướng doanh thu hàng tháng"
    result_str = await agent.process_csv_request(
        query=query,
        csv_content=csv_bytes,
        filename="test_sales.csv",
        session_id="test_session_123"
    )

    res = json.loads(result_str)
    print("=== TEST RESULT SUMMARY ===")
    print("Status:", res.get("status"))
    print("Type:", res.get("type"))

    spec = res.get("dashboard_spec", {})
    print("Layout Type:", spec.get("layout_type"))
    print("Number of charts in spec:", len(spec.get("charts", [])))

    if spec.get("charts"):
        primary = spec["charts"][0]
        print("Primary Chart Title:", primary.get("title"))
        print("Primary Chart Type:", primary.get("type"))
        print("Number of X-axis categories (months):", len(primary.get("x_data", [])))
        print("X-axis Sample Data:", primary.get("x_data", [])[:5])
        print("Number of Series:", len(primary.get("series", [])))
        if primary.get("series"):
            s0 = primary["series"][0]
            print("Series 0 Data Points:", len(s0.get("data", [])))
            print("Series 0 markLine present:", "markLine" in s0)
            if "markLine" in s0:
                print("markLine Config:", json.dumps(s0["markLine"], ensure_ascii=False, indent=2))

    # Assertions
    assert spec.get("layout_type") == "single_chart", f"Expected single_chart, got {spec.get('layout_type')}"
    assert len(spec.get("charts", [])) == 1, f"Expected 1 chart, got {len(spec.get('charts', []))}"
    assert len(primary.get("x_data", [])) <= 30, f"Expected ~12-24 months, got {len(primary.get('x_data', []))}"
    assert len(primary.get("series", [])) == 1, f"Expected exactly 1 series (no 2nd overlapping line), got {len(primary.get('series', []))}"
    assert "markLine" in primary["series"][0], "Expected markLine in primary series"
    assert primary["series"][0]["markLine"]["data"][0]["type"] == "average", "markLine data type should be 'average'"
    
    print("\n✅ ALL BACKEND ASSERTIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
