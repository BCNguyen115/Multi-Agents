import sys
sys.path.insert(0, ".")
import re
import pandas as pd
from src.agents.data_agent.agent import classify_columns_advanced, build_universal_archetype_charts

# Let's inspect current build_universal_archetype_charts output
df = pd.read_csv('dataset/test_data/ecommerce_sales_analytics_5000.csv')
cls = classify_columns_advanced(df)
print("Current cls keys:", list(cls.keys()))
