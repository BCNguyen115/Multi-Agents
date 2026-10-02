import sys
sys.path.insert(0, ".")
import pandas as pd
from src.agents.data_agent.agent import (
    classify_columns,
    classify_columns_advanced,
    build_universal_archetype_charts,
    validate_and_correct_chart_specs,
)
from src.orchestrator.verifier import verify_dashboard_spec, audit_chart_spec

df = pd.read_csv('dataset/test_data/ecommerce_sales_analytics_5000.csv')

# 1. Test classify_columns from prompt 3.1
cols = classify_columns(df)
print("classify_columns result:")
for k, v in cols.items():
    print(f"  {k}: {v}")

assert 'customer_id' in cols['id_cols']
assert 'order_id' in cols['id_cols']
assert 'revenue' in cols['valid_measures']
assert 'customer_id' not in cols['valid_measures']
assert 'order_date' in cols['temporal_cols']
print("classify_columns assertions passed!")

# 2. Test classify_columns_advanced
cls_adv = classify_columns_advanced(df)
assert 'customer_id' not in cls_adv['numeric_metrics']
assert 'order_id' not in cls_adv['numeric_metrics']
assert 'order_date' not in cls_adv['entity_cols']
assert 'order_id' not in cls_adv['entity_cols']
print("classify_columns_advanced assertions passed!")

# 3. Test build_universal_archetype_charts + validate_and_correct_chart_specs
charts = build_universal_archetype_charts(df, cls_adv, 'EXECUTIVE_STRATEGIC_OVERVIEW')
dashboard_spec = {
    "charts": charts,
    "archetype": "EXECUTIVE_STRATEGIC_OVERVIEW",
    "layout_type": "full_dashboard",
    "kpi_cards": [
        {"title": "Tổng Doanh Thu", "value": "1,000,000", "unit": "USD"},
        {"title": "Tổng Số Đơn Hàng", "value": "5,000", "unit": "Đơn"},
        {"title": "Giá Trị Trung Bình", "value": "200", "unit": "USD"}
    ]
}

corrected = validate_and_correct_chart_specs(dashboard_spec, cls_adv, df)
print("\nValidated charts:")
for i, c in enumerate(corrected["charts"]):
    print(f"  Chart {i+1}: {c.get('title')} | dim={c.get('dimension')} | meas={c.get('measure')} | type={c.get('type')}")
    # Invariant 1: No ID as measure with SUM/AVG
    meas = c.get('measure')
    agg = c.get('aggregation', 'SUM')
    assert meas not in ['customer_id', 'order_id'], f"ID in measure: {meas}"
    # Invariant 4: No date in bar
    if c.get('dimension') in ['order_date']:
        assert c.get('type') in ['area', 'line'], f"Date in bar chart: {c.get('type')}"
    # Invariant 3: Semantic coherence
    if 'region' in c.get('title', '').lower():
        assert c.get('dimension') == 'region', f"Region mismatch: {c.get('dimension')}"

# 4. Test verifier
is_valid, msg = verify_dashboard_spec(df, corrected)
print(f"\nverify_dashboard_spec result: {is_valid} | msg: {msg}")
assert is_valid, f"Verification failed: {msg}"

# 5. Test verifier catches banned SUM on customer_id
bad_chart = {
    "type": "bar",
    "dimension": "product_category",
    "measure": "customer_id",
    "aggregation": "SUM",
    "title": "Tổng Customer ID"
}
passed, err = audit_chart_spec(bad_chart, cls_adv)
print(f"\nAudit bad chart test (SUM on customer_id): passed={passed}, err='{err}'")
assert not passed
assert "Cột ID" in err

# 6. Test verifier catches date in bar ranking
bad_date_chart = {
    "type": "bar",
    "dimension": "order_date",
    "measure": "revenue",
    "aggregation": "SUM",
    "title": "Top 15 Ngày"
}
passed, err = audit_chart_spec(bad_date_chart, cls_adv)
print(f"Audit bad date chart test: passed={passed}, err='{err}'")
assert not passed
assert "Cột ngày tháng" in err

# 7. Test verifier catches Title vs Dimension mismatch
bad_mismatch_chart = {
    "type": "donut",
    "dimension": "product_category",
    "measure": "revenue",
    "aggregation": "SUM",
    "title": "Tỷ Trọng Cơ Cấu Theo Region"
}
passed, err = audit_chart_spec(bad_mismatch_chart, cls_adv)
print(f"Audit mismatch chart test: passed={passed}, err='{err}'")
assert not passed
assert "Lệch pha ngữ nghĩa" in err

print("\nALL INVARIANT AUDIT TESTS PASSED 100%!")
