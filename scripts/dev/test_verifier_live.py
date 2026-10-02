import asyncio
import json
import sys
sys.path.insert(0, ".")
import pandas as pd
from src.agents.data_agent.agent import DataAnalystAgent
from src.orchestrator.verifier import verify_dashboard_spec
from src.shared.llm_client import LLMClient

async def test():
    df = pd.read_csv("dataset/test_data/ecommerce_sales_analytics_5000.csv")
    llm = LLMClient()
    agent = DataAnalystAgent(llm_client=llm)
    query = "Dựng dashboard phân tích doanh thu và cơ cấu kinh doanh từ file bán hàng"
    res_str = await agent.process_csv_request(
        query=query,
        csv_content=df.to_csv(index=False),
        filename="ecommerce_sales_analytics_5000.csv",
        session_id="test_session_verifier"
    )
    res = json.loads(res_str)
    spec = res.get("dashboard_spec", {})
    charts = spec.get("charts", [])
    print(f"Spec generated with {len(charts)} charts")
    for i, c in enumerate(charts):
        print(f"Chart {i+1}: title='{c.get('title')}', type='{c.get('type')}', dim='{c.get('dimension')}', meas='{c.get('measure')}'")
    is_valid, msg = verify_dashboard_spec(df, spec)
    print("VERIFY RESULT:", is_valid, msg)

if __name__ == "__main__":
    asyncio.run(test())
