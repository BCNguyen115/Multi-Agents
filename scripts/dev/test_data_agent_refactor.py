import asyncio
import pandas as pd
import json
import sys
from unittest.mock import MagicMock

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Mock litellm module if not installed
try:
    import litellm
except ImportError:
    mock_litellm = MagicMock()
    sys.modules['litellm'] = mock_litellm

from src.agents.data_agent.agent import DataAnalystAgent

async def test_pipeline():
    # Create sample dataset
    data = {
        "order_date": ["2024-01-05", "2024-01-15", "2024-02-10", "2024-02-20", "2024-03-05", "2024-03-25", "2024-04-12", "2024-04-28"],
        "revenue": [12000, 15000, 22000, 18000, 30000, 25000, 14000, 16000],
        "quantity": [10, 15, 20, 18, 30, 25, 14, 16],
        "category": ["Electronics", "Clothing", "Electronics", "Clothing", "Electronics", "Clothing", "Electronics", "Clothing"],
        "region": ["North", "South", "North", "South", "North", "South", "North", "South"]
    }
    df = pd.DataFrame(data)
    
    dummy_llm = MagicMock()
    dummy_llm.chat_completion = MagicMock(side_effect=Exception("LLM offline fallback test"))
    
    agent = DataAnalystAgent(llm_client=dummy_llm)
    
    user_query = "Tạo biểu đồ đường (Line Chart) biểu diễn xu hướng doanh thu hàng tháng và đường xu hướng trung bình"
    print("User Query:", user_query)
    
    # STEP 1: Parse Intent
    intent = await agent._parse_user_chart_intent(user_query, df.columns.tolist())
    print("\n--- STEP 1: PARSED INTENT ---")
    print(json.dumps(intent, indent=2, ensure_ascii=False))
    
    # STEP 2: Execute Aggregations
    chart_data = agent._execute_data_aggregation(df, intent)
    print("\n--- STEP 2: CHART DATA ---")
    print(json.dumps({k: v for k, v in chart_data.items() if k != "data_records"}, indent=2, ensure_ascii=False))
    
    # STEP 3: Build Custom ECharts Spec
    primary_spec = agent._build_custom_echarts_spec(intent, chart_data)
    print("\n--- STEP 3: ECHARTS SPEC ---")
    print(json.dumps(primary_spec, indent=2, ensure_ascii=False))
    
    # STEP 4: Storyteller
    story_text = await agent._run_business_storyteller({"chart_data": chart_data, "chart_intent": intent}, "")
    print("\n--- STEP 4: STORYTELLING INSIGHTS ---")
    print(story_text)

    # Verification Assertions
    assert intent["primary_chart_type"] == "line", f"Expected 'line', got {intent['primary_chart_type']}"
    assert intent["x_axis"] == "order_date", f"Expected 'order_date', got {intent['x_axis']}"
    assert intent["group_by_type"] == "monthly", f"Expected 'monthly', got {intent['group_by_type']}"
    assert primary_spec["type"] == "line", f"Expected primary_spec type 'line', got {primary_spec['type']}"
    assert len(primary_spec["series"]) == 2, f"Expected 2 series (main line + avg benchmark), got {len(primary_spec['series'])}"
    assert primary_spec["series"][1]["name"] == "Mức Trung Bình", "Secondary benchmark series missing or misnamed"
    
    print("\n[SUCCESS] Refactored Data Agent Swarm pipeline executed and verified 100%!")

if __name__ == "__main__":
    asyncio.run(test_pipeline())
