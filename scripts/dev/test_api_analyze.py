import asyncio
import json
import sys
sys.path.insert(0, ".")
import pandas as pd
from src.agents.data_agent.agent import DataAnalystAgent
from src.shared.llm_client import LLMClient

async def main():
    df = pd.read_csv("dataset/test_data/ecommerce_sales_analytics_5000.csv")
    llm = LLMClient()
    agent = DataAnalystAgent(llm_client=llm)
    
    query = "Dựng full executive dashboard phân tích doanh thu bán hàng và hiệu quả kinh doanh"
    print(f"Running DataAnalystAgent on query: '{query}'...")
    res_json_str = await agent.process_csv_request(
        query=query,
        csv_content=df.to_csv(index=False),
        filename="ecommerce_sales_analytics_5000.csv",
        session_id="test_session_ecommerce"
    )
    
    res = json.loads(res_json_str)
    spec = res.get("dashboard_spec", {})
    charts = spec.get("charts", [])
    print(f"\n--- GENERATED DASHBOARD SPEC ---")
    print(f"Status: {res.get('status')}")
    print(f"Number of Charts: {len(charts)}")
    for i, c in enumerate(charts):
        title = c.get("title")
        c_type = c.get("type")
        dim = c.get("dimension")
        meas = c.get("measure")
        agg = c.get("aggregation")
        subtitle = c.get("subtitle")
        data_preview = c.get("data", [])[:3]
        print(f"\nChart #{i+1}:")
        print(f"  Title: {title}")
        print(f"  Subtitle: {subtitle}")
        print(f"  Type: {c_type} | Dim: {dim} | Measure: {meas} | Agg: {agg}")
        print(f"  Data Preview: {data_preview}")
        
        # Invariants checks
        assert meas not in ["customer_id", "order_id"], f"Chart #{i+1} has banned ID measure: {meas}"
        if dim in ["order_date"]:
            assert c_type in ["area", "line"], f"Chart #{i+1} has date ranking in {c_type}"
        if "region" in str(title).lower():
            assert dim == "region", f"Chart #{i+1} Title mentions region but dim is {dim}"
        if "ngành hàng" in str(title).lower() or "category" in str(title).lower():
            assert dim in ["product_category", "category"], f"Chart #{i+1} Title mentions category but dim is {dim}"
            
    print("\nSUCCESS: All dashboard charts fully satisfy Data Reasoning Invariants!")

if __name__ == "__main__":
    asyncio.run(main())
