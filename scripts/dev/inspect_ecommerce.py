import sys
sys.path.insert(0, ".")
import pandas as pd
from src.agents.data_agent.agent import classify_columns_advanced, build_universal_archetype_charts

df = pd.read_csv('dataset/test_data/ecommerce_sales_analytics_5000.csv')
cls = classify_columns_advanced(df)
print('numeric_metrics:', cls.get('numeric_metrics'))
print('entity_cols:', cls.get('entity_cols'))
print('donut_pie_cat_cols:', cls.get('donut_pie_cat_cols'))
print('temporal_cols:', cls.get('temporal_cols'))
charts = build_universal_archetype_charts(df, cls, 'EXECUTIVE_STRATEGIC_OVERVIEW')
print('Charts generated:', len(charts))
for i, c in enumerate(charts):
    print(f"Chart {i+1}: {c.get('title')} | type={c.get('type')} | dim={c.get('dimension')} | meas={c.get('measure')} | agg={c.get('aggregation')}")
