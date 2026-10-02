"""Phase 0/1 regressions: multi-format ingest, Unicode labels, value-based roles, aggregation policy, dates."""
import io
import json

import numpy as np
import pandas as pd
import pytest

from src.agents.data_agent.ingest import load_dataset, safe_read_csv
from src.agents.data_agent.profiler import (
    AGG_AVG,
    AGG_SUM,
    ROLE_BOOLEAN,
    ROLE_HIGH_CARDINALITY,
    ROLE_IDENTIFIER,
    ROLE_LOW_CARDINALITY,
    ROLE_MEASURE,
    ROLE_ORDINAL,
    ROLE_RATIO,
    ROLE_TEMPORAL,
    ROLE_TEXT,
    UNIT_CURRENCY,
    choose_time_grain,
    is_monetary_name,
    parse_datetimes,
    profile_dataframe_universal,
)
from src.shared.dataset_reader import DatasetReadError, sniff_delimiter

N = 240
rng = np.random.default_rng(7)


# ---------------------------------------------------------------- ingest (B1, B2, A7, B9)
@pytest.mark.parametrize("delim", [";", "\t", "|", ","])
def test_any_common_delimiter_is_read_as_columns(delim):
    text = delim.join(["a", "b", "c"]) + "\n" + "\n".join(delim.join(map(str, r)) for r in [(1, 2, 3), (4, 5, 6), (7, 8, 9)])
    ds = load_dataset(text)
    assert list(ds.df.columns) == ["a", "b", "c"] and len(ds.df) == 3
    assert ds.meta["delimiter"] == delim


def test_quoted_delimiters_do_not_confuse_sniffing():
    assert sniff_delimiter('name,note\n"a;b;c",x\n"d;e;f",y\n') == ","


def test_non_latin_headers_survive_with_original_labels():
    raw = "売上,顧客名,Цена,Total Price,Tên Sản Phẩm\n1,a,2,3,x\n4,b,5,6,y\n".encode("utf-8")
    ds = load_dataset(raw)
    assert not any(c.startswith("col_") for c in ds.df.columns)
    assert "売上" in ds.df.columns and ds.labels["売上"] == "売上"
    assert ds.labels["total_price"] == "Total Price"
    assert ds.labels["ten_san_pham"] == "Tên Sản Phẩm"
    assert "цена" in ds.df.columns


def test_duplicate_and_blank_headers_get_unique_ids_and_labels():
    ds = load_dataset("a,a,,b\n1,2,3,4\n5,6,7,8\n")
    assert len(set(ds.df.columns)) == 4
    assert ds.labels[ds.df.columns[1]] == "a (2)"


@pytest.mark.parametrize("raw,expected", [
    ("$1,200.50", 1200.5), ("1.234,56", 1234.56), ("12,5", 12.5), ("(500)", -500.0), ("1200", 1200.0),
])
def test_number_text_is_understood(raw, expected):
    ds = load_dataset(f'v\n"{raw}"\n"{raw}"\n"{raw}"\n')  # real CSVs quote values that contain the delimiter
    assert ds.df["v"].iloc[0] == pytest.approx(expected)


def test_percent_and_currency_flags_and_leading_zero_codes():
    ds = load_dataset("rate,price,zip\n12%,$5,00123\n50%,$7,00456\n25%,$9,00789\n")
    assert ds.df["rate"].tolist() == [0.12, 0.5, 0.25]
    assert ds.meta["percent_cols"] == ["rate"] and ds.meta["currency_cols"] == ["price"]
    assert ds.df["zip"].tolist() == ["00123", "00456", "00789"]  # codes keep their zeros


def test_large_tables_are_sampled_deterministically_and_disclosed():
    text = "id,val\n" + "\n".join(f"{i},{i * 2}" for i in range(500))
    a, b = load_dataset(text, max_rows=100), load_dataset(text, max_rows=100)
    assert len(a.df) == 100 and a.meta["sampled"] and a.meta["rows_total"] == 500
    assert a.df.equals(b.df) and a.df["id"].is_monotonic_increasing
    assert {"code": "sampled", "rows_used": 100, "rows_total": 500} in a.meta["notes"]
    assert len(safe_read_csv(text, max_rows=50)) == 50


def test_excel_parquet_json_uploads():
    frame = pd.DataFrame({"city": ["a", "b", "c"], "sales": [1.5, 2.5, 3.5]})
    xlsx = io.BytesIO()
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Sheet1", index=False)
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="tiny", index=False)
    excel = load_dataset(xlsx.getvalue(), "book.xlsx")
    assert excel.meta["format"] == "excel" and excel.meta["sheet"] == "Sheet1"
    assert {"code": "multi_sheet", "count": 2, "sheet": "Sheet1"} in excel.meta["notes"]

    parquet = load_dataset(frame.to_parquet(), "t.parquet")
    assert parquet.meta["format"] == "parquet" and parquet.df["sales"].sum() == 7.5

    as_json = load_dataset(json.dumps({"data": frame.to_dict("records")}), "t.json")
    assert as_json.meta["format"] == "json" and len(as_json.df) == 3


@pytest.mark.parametrize("payload", [b"", b"a,b\n", b"\n\n"])
def test_empty_uploads_raise_a_clear_error(payload):
    with pytest.raises(DatasetReadError) as err:
        load_dataset(payload)
    assert err.value.code == "empty"


def test_legacy_xls_is_rejected_with_guidance():
    with pytest.raises(DatasetReadError) as err:
        load_dataset(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 50, "old.xls")
    assert err.value.code == "unsupported"


# ---------------------------------------------------------------- dates
def test_iso_dates_and_year_requirement():
    dates, _ = parse_datetimes(pd.Series(pd.date_range("2023-01-01", periods=30).strftime("%Y-%m-%d")))
    assert dates is not None and dates.iloc[0] == pd.Timestamp("2023-01-01")
    months = pd.Series(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jan", "Feb"] * 5)
    assert parse_datetimes(months)[0] is None  # a month *name* is not a date


def test_day_first_is_inferred_from_values_and_ambiguity_is_flagged():
    unambiguous = pd.Series(["13/02/2024", "14/02/2024", "15/02/2024", "16/02/2024", "17/02/2024", "18/02/2024"])
    parsed, info = parse_datetimes(unambiguous)
    assert parsed.iloc[0] == pd.Timestamp("2024-02-13") and not info["ambiguous"]
    ambiguous = pd.Series([f"0{d}/03/2024" for d in range(1, 8)])
    _, info = parse_datetimes(ambiguous)
    assert info["ambiguous"]


def test_compact_integer_dates_and_plain_numbers():
    compact, _ = parse_datetimes(pd.Series([20240101 + i for i in range(20)]))
    assert compact is not None and compact.iloc[3] == pd.Timestamp("2024-01-04")
    assert parse_datetimes(pd.Series(range(1000, 1030)))[0] is None


def test_time_grain_scales_with_span():
    day = choose_time_grain(pd.Series(pd.date_range("2024-01-01", periods=30, freq="D")))
    month = choose_time_grain(pd.Series(pd.date_range("2022-01-01", periods=900, freq="D")))
    year = choose_time_grain(pd.Series(pd.date_range("1990-01-01", periods=40, freq="365D")))
    assert (day["grain"], month["grain"], year["grain"]) == ("day", "month", "year")


# ---------------------------------------------------------------- roles (B4, B5, B6, B7)
def _frame():
    return pd.DataFrame({
        "customer_uuid": [f"{i:08x}-1111-2222-3333-{i:012x}" for i in range(N)],
        "order_no": range(1, N + 1),
        "placed_on": pd.date_range("2023-01-01", periods=N, freq="D"),
        "day_of_week": rng.choice(["Mon", "Tue", "Wed", "Thu", "Fri"], N),
        "smartphone_price": rng.uniform(100, 900, N).round(2),
        "dynamic_price": rng.uniform(5, 50, N).round(2),
        "keyword_count": rng.integers(0, 200, N),
        "quantity": rng.integers(1, 6, N),
        "rating": rng.integers(1, 6, N),
        "discount": rng.uniform(0, 0.4, N).round(3),
        "is_member": rng.choice(["yes", "no"], N),
        "country_code": rng.choice(["VN", "US", "JP", "DE", "FR"], N),
        "product": [f"p{i % 40}" for i in range(N)],
        "review": ["this is a long free text review " * 3 + str(i) for i in range(N)],
    })


def test_roles_come_from_values_not_substrings():
    roles = profile_dataframe_universal(_frame())["role_map"]
    assert roles["customer_uuid"] == ROLE_IDENTIFIER
    assert roles["order_no"] == ROLE_IDENTIFIER  # unique running sequence
    assert roles["placed_on"] == ROLE_TEMPORAL
    assert roles["day_of_week"] == ROLE_LOW_CARDINALITY  # contains "day" but is not a date (B5)
    assert roles["smartphone_price"] == ROLE_MEASURE  # contains "phone" but is not an id (B4)
    assert roles["dynamic_price"] == ROLE_MEASURE  # contains "nam" (B6)
    assert roles["keyword_count"] == ROLE_MEASURE  # contains "key" (B4)
    assert roles["rating"] == ROLE_ORDINAL
    assert roles["discount"] == ROLE_RATIO
    assert roles["is_member"] == ROLE_BOOLEAN
    assert roles["country_code"] == ROLE_LOW_CARDINALITY  # a *code* that is a category, not an id
    assert roles["product"] == ROLE_HIGH_CARDINALITY
    assert roles["review"] == ROLE_TEXT


def test_aggregation_policy_uses_sum_only_with_additivity_evidence():
    profile = profile_dataframe_universal(_frame())
    policies = profile["policies"]
    assert policies["quantity"]["agg"] == AGG_SUM  # additive count
    assert policies["keyword_count"]["agg"] == AGG_SUM
    assert policies["smartphone_price"]["agg"] == AGG_AVG  # a price is not summed
    assert policies["rating"]["agg"] == AGG_AVG
    assert policies["discount"]["agg"] == AGG_AVG
    assert policies["smartphone_price"]["unit_kind"] == UNIT_CURRENCY
    assert profile["measures"][0] in ("keyword_count", "quantity", "smartphone_price", "dynamic_price")


def test_time_axis_and_quality_warnings():
    frame = _frame()
    frame.loc[:100, "review"] = None
    profile = profile_dataframe_universal(frame)
    assert profile["time"]["primary"] == "placed_on" and profile["time"]["grain"] in ("week", "month")
    codes = {w["code"] for w in profile["quality"]["warnings"]}
    assert "missing_high" in codes


def test_year_columns_are_ordinal_not_measures():
    frame = pd.DataFrame({"debut_year": rng.integers(1995, 2024, N), "streams": rng.integers(1_000, 90_000, N)})
    roles = profile_dataframe_universal(frame)["role_map"]
    assert roles["debut_year"] == ROLE_ORDINAL and roles["streams"] == ROLE_MEASURE


def test_profile_of_tiny_and_degenerate_tables_does_not_crash():
    assert profile_dataframe_universal(pd.DataFrame({"a": [1]}))["total_rows"] == 1
    profile = profile_dataframe_universal(pd.DataFrame({"a": [None, None], "b": ["x", "x"]}))
    assert profile["measures"] == [] and not profile["has_temporal"]


def test_monetary_hint_is_token_based():
    assert is_monetary_name("unit_price") and is_monetary_name("doanh_thu") and is_monetary_name("Gia")
    assert not is_monetary_name("plays_millions") and not is_monetary_name("giant_count")
