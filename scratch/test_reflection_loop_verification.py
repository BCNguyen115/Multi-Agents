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
    # Dataset with Debut Year (integers)
    df = pd.DataFrame({
        "artist": ["Artist A", "Artist B", "Artist C", "Artist D", "Artist E"],
        "Debut Year": [2006, 2008, 2013, 2018, 2021],
        "sales": [15000, 22000, 35000, 48000, 52000],
        "agency": ["Agency X", "Agency Y", "Agency X", "Agency Y", "Agency Z"]
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")

    # Mock LLM Client
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = "📈 Diễn biến: Doanh số tăng dần theo Debut Year từ 2006 đến 2021.\n🔍 Nguyên nhân: Phát triển quy mô thị trường.\n🎯 Khuyến nghị: Đầu tư nghệ sĩ mới."
    mock_resp.choices = [MagicMock(message=mock_msg)]
    mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

    agent = DataAnalystAgent(llm_client=mock_llm)

    query = "Vẽ biểu đồ đường xu hướng doanh số theo Debut Year"
    result_str = await agent.process_csv_request(
        query=query,
        csv_content=csv_bytes,
        filename="kpop_artists.csv",
        session_id="test_reflection_loop"
    )

    res = json.loads(result_str)
    print("=== REFLECTION SWARM LOOP TEST RESULT ===")
    print("Status:", res.get("status"))

    spec = res.get("dashboard_spec", {})
    print("totalRows:", spec.get("totalRows"))
    print("totalColumns:", spec.get("totalColumns"))
    print("total_rows:", spec.get("total_rows"))
    print("total_cols:", spec.get("total_cols"))

    charts = spec.get("charts", [])
    print("Charts count:", len(charts))
    if charts:
        p_chart = charts[0]
        print("Primary Chart Title:", p_chart.get("title"))
        print("Primary Chart X-axis Data:", p_chart.get("x_data", []))
        
        # Verify 1970-01 is NOT in x_data
        x_str_list = [str(x) for x in p_chart.get("x_data", [])]
        print("X-axis String Values:", x_str_list)

        assert not any("1970-01" in x for x in x_str_list), "ERROR: Found 1970-01 Epoch Date bug!"
        assert "2006" in x_str_list or 2006 in p_chart.get("x_data", []), "Expected year 2006 in X-axis data"

    # Test Sub-Agent A directly
    chart_valid, chart_feedback = agent._evaluate_chart_data_quality(df, spec)
    print("Sub-Agent A Evaluation:", "VALID" if chart_valid else f"INVALID: {chart_feedback}")
    assert chart_valid, f"Sub-Agent A failed: {chart_feedback}"

    # Test Sub-Agent B directly
    story_valid, story_feedback = await agent._evaluate_storytelling_quality(df, spec)
    print("Sub-Agent B Evaluation:", "VALID" if story_valid else f"INVALID: {story_feedback}")
    assert story_valid, f"Sub-Agent B failed: {story_feedback}"

    # Assert metric keys exist
    assert spec.get("totalRows") == 5, f"Expected totalRows=5, got {spec.get('totalRows')}"
    assert spec.get("totalColumns") == 4, f"Expected totalColumns=4, got {spec.get('totalColumns')}"

    print("\n✅ ALL REFLECTION SWARM LOOP ASSERTIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
