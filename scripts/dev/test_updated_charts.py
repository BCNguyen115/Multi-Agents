import sys
sys.path.insert(0, ".")
import re
import math
import pandas as pd

ID_COLUMN_REGEX = re.compile(r"(?i)(_id|id$|^id_|stt|code|key|uuid|phone|postal|zip)")

SEMANTIC_MEASURE_PRIORITY = {
    "revenue": 100, "sales": 100, "doanh_thu": 100, "amount": 90, "total_revenue": 100,
    "price": 85, "unit_price": 85, "cost": 80, "profit": 85, "total_streams": 85,
    "salary": 80, "tien": 80, "gia": 80, "fee": 75, "spend": 80, "spent": 80,
    "quantity": 70, "volume": 70, "so_luong": 70, "views": 65, "clicks": 65,
    "delivery_days": 60, "streams": 70, "plays": 70, "units": 70,
    "rating": 50, "customer_rating": 50, "discount": 45, "score": 45, "margin": 45,
}

def is_identifier_col(col_name: str, ser: pd.Series = None, total_rows: int = 0) -> bool:
    cn = str(col_name).lower().strip()
    if ID_COLUMN_REGEX.search(cn):
        return True
    if cn in ["id", "_id", "guid", "uuid", "row_id", "index", "stt", "pk", "uid"]:
        return True
    if ser is not None and pd.api.types.is_numeric_dtype(ser) and total_rows > 10:
        if ser.nunique() == total_rows and (cn.endswith("_num") or cn.endswith("number") or "code" in cn):
            return True
    return False

def get_measure_semantic_score(col_name: str, ser: pd.Series) -> float:
    cn = str(col_name).lower().strip()
    base_score = 10.0
    for keyword, weight in SEMANTIC_MEASURE_PRIORITY.items():
        if keyword in cn:
            base_score = max(base_score, float(weight))
    try:
        num_ser = pd.to_numeric(ser, errors="coerce").fillna(0.0)
        tot = float(abs(num_ser).sum())
        std_val = float(num_ser.std()) if len(num_ser) > 1 else 0.0
        mag_boost = min(20.0, math.log10(tot + 1.0) * 2.0) if tot > 0 else 0.0
        return base_score + mag_boost + (1.0 if std_val > 0 else 0.0)
    except Exception:
        return base_score

df = pd.read_csv('dataset/test_data/ecommerce_sales_analytics_5000.csv')
total_rows = len(df)
cardinality = {str(c): int(df[c].nunique()) for c in df.columns}

id_cols = [str(c) for c in df.columns if is_identifier_col(c, df[c], total_rows)]
temporal_cols = ['order_date']

valid_measures = [
    str(c) for c in df.columns
    if pd.api.types.is_numeric_dtype(df[c]) and str(c) not in id_cols and str(c) not in temporal_cols and not any(k in str(c).lower() for k in ["year", "nam", "rank", "stt"])
]
valid_measures.sort(key=lambda m: get_measure_semantic_score(m, df[m]), reverse=True)

categorical_low = [
    str(c) for c in df.columns
    if str(c) not in id_cols and str(c) not in temporal_cols and str(c) not in valid_measures and 2 <= cardinality[str(c)] <= 7
]
categorical_high = [
    str(c) for c in df.columns
    if str(c) not in id_cols and str(c) not in temporal_cols and str(c) not in valid_measures and cardinality[str(c)] > 7
]

classified = {
    "total_rows": total_rows,
    "total_cols": len(df.columns),
    "cardinality": cardinality,
    "id_cols": id_cols,
    "valid_measures": valid_measures,
    "categorical_low": categorical_low,
    "categorical_high": categorical_high,
    "temporal_cols": temporal_cols,
    "donut_pie_cat_cols": categorical_low,
    "low_cardinality_dims": categorical_low,
    "valid_category_cols": categorical_low + categorical_high,
    "high_cardinality_cols": categorical_high,
    "high_cardinality_dims": categorical_high,
    "numeric_metrics": valid_measures,
    "continuous_measures": valid_measures,
    "ratio_metrics": ['discount'],
    "entity_cols": categorical_high or categorical_low,
    "recommended_archetype_hint": "EXECUTIVE_STRATEGIC_OVERVIEW",
    "has_temporal": True,
    "primary_date_col": "order_date",
}

from src.agents.data_agent.agent import build_universal_archetype_charts

charts = build_universal_archetype_charts(df, classified, "EXECUTIVE_STRATEGIC_OVERVIEW")
print(f"Generated {len(charts)} charts:")
for i, c in enumerate(charts):
    print(f"Chart {i+1}: title='{c.get('title')}' | type={c.get('type')} | dim={c.get('dimension')} | meas={c.get('measure')} | agg={c.get('aggregation')}")
