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

id_cols = []
valid_measures = []
categorical_low = []
categorical_high = []
temporal_cols = []

for col in df.columns:
    col_str = str(col)
    col_lower = col_str.lower().strip()
    ser = df[col]
    nu = cardinality[col_str]
    
    # 1. Phát hiện cột ID
    if ID_COLUMN_REGEX.search(col_lower) or col_lower in ["id", "_id", "guid", "uuid", "row_id", "index", "stt", "pk", "uid"]:
        id_cols.append(col_str)
        continue
        
    # 2. Phát hiện cột thời gian
    if any(k in col_lower for k in ["date", "time", "created_at", "ngay", "thang"]):
        temporal_cols.append(col_str)
        continue
        
    # 3. Phát hiện cột số đo (Measures)
    if pd.api.types.is_numeric_dtype(ser):
        if not any(k in col_lower for k in ["year", "nam", "rank", "stt"]):
            valid_measures.append(col_str)
        if 2 <= nu <= 7 and total_rows > 20:
            categorical_low.append(col_str)
        continue
        
    # 4. Cột phân loại theo Cardinality
    if 2 <= nu <= 7:
        categorical_low.append(col_str)
    elif nu > 7:
        categorical_high.append(col_str)

valid_measures.sort(key=lambda m: get_measure_semantic_score(m, df[m]), reverse=True)

print("ID cols:", id_cols)
print("Temporal cols:", temporal_cols)
print("Valid measures (ranked):", valid_measures)
print("Categorical low:", categorical_low)
print("Categorical high:", categorical_high)
