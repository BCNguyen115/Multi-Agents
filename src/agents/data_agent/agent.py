"""Data Analyst Agent — Multi-Agent Swarm Dashboard Pipeline with PEV Self-Correction Loop.

Architecture:
  Sub-Agent 1: Data Analytics Executor (`_run_data_exploration`)
      - Pure Pandas / DuckDB safe Python execution to compute shapes, column dtypes,
        KPIs, and group-by aggregations.
  Sub-Agent 2: Dashboard Layout Architect (`_run_layout_architect`)
      - Plans Skeleton Dashboard with 12-column grid layout system (col-span-12, col-span-7, col-span-5).
  Sub-Agent 3: Chart Spec Builder (`_run_chart_generator`)
      - Generates detailed chart specs (ECharts / Plotly / Recharts Spec) with type casting & formatting.
  Sub-Agent 4: Executive Storyteller (`_run_business_storyteller`)
      - Synthesizes 3-part business insight commentary: Diễn Biến -> Nguyên Nhân -> Khuyến Nghị.
  Sub-Agent 5: Verifier & Evaluator Node (`_verify_dashboard_quality`)
      - Validates 12-col grid alignment, null/NaN freedom, and key mapping integrity.

Workflow:
  Executes in a PEV Self-Correction loop (`while retry_count < max_retries:`) up to 3 retries.
"""

import io
import json
import logging
import math
import re
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.agents.base_agent import BaseAgent
from src.agents.data_agent.sandbox import SafePythonSandbox, SandboxResult
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.csv_sanitizer import sanitize_column_names

logger: logging.Logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Safety — forbidden patterns in generated code
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS: list[str] = [
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\b__import__\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bopen\s*\(",
    r"\bshutil\b",
    r"\bsys\.exit\b",
    r"\bos\.remove\b",
    r"\bos\.rmdir\b",
    r"\bos\.unlink\b",
]

_FORBIDDEN_RE: re.Pattern[str] = re.compile(
    "|".join(_FORBIDDEN_PATTERNS), re.IGNORECASE
)

def strip_emojis(text: str) -> str:
    """Xóa sạch mọi ký tự emoji thừa khỏi chuỗi văn bản."""
    if not text:
        return ""
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff"
        "\uD800-\uDBFF\uDC00-\uDFFF"
        "\u2600-\u26FF\u2700-\u27BF"
        "\u2B50\u2B55\u231A\u231B\u23E9-\u23EC\u23F0\u23F3]+",
        flags=re.UNICODE,
    )
    cleaned = emoji_pattern.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


# Maximum CSV size to accept (10 MB)
_MAX_CSV_BYTES: int = 10 * 1024 * 1024
_MAX_PREVIEW_ROWS: int = 5
_DEFAULT_MAX_RETRIES: int = 3


def safe_read_csv(csv_content: str | bytes, max_rows: int = 50000) -> pd.DataFrame:
    """Read CSV content safely handling encoding and delimiter variations.

    Limits max rows to 50,000 by default to prevent Out-Of-Memory (OOM) on large files.
    """
    if isinstance(csv_content, str):
        buffer: io.StringIO | io.BytesIO = io.StringIO(csv_content)
    else:
        buffer = io.BytesIO(csv_content)

    encodings_to_try = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    df: Optional[pd.DataFrame] = None

    for encoding in encodings_to_try:
        try:
            if isinstance(csv_content, bytes):
                df = pd.read_csv(io.BytesIO(csv_content), encoding=encoding)
            else:
                buffer.seek(0)
                df = pd.read_csv(buffer, encoding=encoding)
            break
        except (UnicodeDecodeError, Exception):
            continue

    if df is None:
        if isinstance(csv_content, bytes):
            df = pd.read_csv(io.BytesIO(csv_content), sep=None, engine="python")
        else:
            buffer.seek(0)
            df = pd.read_csv(buffer, sep=None, engine="python")

    # Standardize column names via centralised sanitiser
    df = sanitize_column_names(df)

    # Protect against memory exhaustion / OOM on large datasets
    if len(df) > max_rows:
        logger.warning(
            "Dataset row count (%d) exceeds max_rows limit (%d). Sampling top %d rows for safe processing.",
            len(df),
            max_rows,
            max_rows,
        )
        df = df.iloc[:max_rows].copy()

    return df


def get_primary_metric_series(df: pd.DataFrame) -> tuple[pd.Series, str, str]:
    """Dynamically determine and extract the primary continuous business metric series.

    Returns:
        tuple[pd.Series, str, str]: (Series, column_name, display_unit)
    """
    total_rows = len(df)
    if total_rows == 0:
        return pd.Series(dtype=float), "", ""

    # Exclude technical IDs
    numeric_cols = [
        c for c in df.select_dtypes(include=[np.number]).columns
        if not str(c).lower().strip() in ["id", "_id", "stt", "index", "guid", "uuid", "row_id", "pk"]
        and not str(c).lower().endswith("_id")
    ]

    continuous_candidates: list[str] = []
    for col in numeric_cols:
        col_lower = str(col).lower()
        if any(pct in col_lower for pct in ["%", "percent", "pct", "ratio", "rate", "share", "margin", "ty_le"]):
            continue
        ser = pd.to_numeric(df[col], errors="coerce").dropna()
        if ser.empty:
            continue
        # Check if year (integers between 1900 and 2050)
        if (ser % 1 == 0).all() and (ser >= 1900).all() and (ser <= 2050).all():
            continue
        continuous_candidates.append(col)

    if not continuous_candidates:
        if numeric_cols:
            best_col = numeric_cols[0]
            return pd.to_numeric(df[best_col], errors="coerce").fillna(0.0), str(best_col), ""
        return pd.Series(0.0, index=df.index), "", ""

    # Rank continuous candidates by total absolute sum and standard deviation
    def candidate_score(c: str) -> float:
        ser = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        total_sum = float(abs(ser).sum())
        std_val = float(ser.std()) if len(ser) > 1 else 0.0
        return total_sum + std_val

    continuous_candidates.sort(key=candidate_score, reverse=True)
    best_col = continuous_candidates[0]
    ser = pd.to_numeric(df[best_col], errors="coerce").fillna(0.0)
    return ser, str(best_col), ""


def get_revenue_series(df: pd.DataFrame) -> pd.Series:
    """Backward compatibility wrapper: returns primary continuous metric series."""
    ser, _, _ = get_primary_metric_series(df)
    return ser


def classify_columns_advanced(df: pd.DataFrame) -> dict[str, Any]:
    """Pure Statistical Profiler for Domain-Agnostic Dataset Characterization.

    Classifies columns purely based on statistical cardinality, mathematical properties,
    and data types without hardcoding specific business domain column names:
      - temporal_cols: Datetime, integer years (1900-2050), or date string patterns.
      - donut_pie_cat_cols: Low-cardinality categorical (2 <= nunique <= 7), unique ratio < 15%.
      - valid_category_cols: Categorical columns suitable for slicers (2 <= nunique <= 25).
      - entity_cols: Non-numeric text columns with high cardinality (nunique >= 5), ranked by diversity.
      - numeric_metrics: Continuous numeric measures with std > 0 and sum > 0, ranked by variance/scale.
      - ratio_metrics: Proportional metrics in [0, 1] or [0, 100] or containing ratio/rate/%.
      - cardinality: Full column -> nunique mapping.
    """
    total_rows = len(df)
    cardinality: dict[str, int] = {str(c): int(df[c].nunique()) for c in df.columns}

    temporal_cols: list[str] = []
    donut_pie_cat_cols: list[str] = []
    valid_category_cols: list[str] = []
    high_cardinality_cols: list[str] = []
    numeric_metrics: list[str] = []
    ratio_metrics: list[str] = []
    entity_cols: list[str] = []

    def is_technical_id_col(col_name: str, ser: pd.Series) -> bool:
        cn = str(col_name).lower().strip()
        if cn in ["id", "_id", "guid", "uuid", "row_id", "index", "stt", "pk", "uid"]:
            return True
        if pd.api.types.is_numeric_dtype(ser) and ser.nunique() == total_rows and total_rows > 10:
            if cn.endswith("_num") or cn.endswith("number") or "code" in cn or cn.endswith("_id") or cn.startswith("id_"):
                return True
        return False

    for col in df.columns:
        n_unique = cardinality[str(col)]
        col_name_lower = str(col).lower()
        ser = df[col]

        if is_technical_id_col(col, ser):
            continue

        # 1. Temporal Detection
        is_temporal = False
        if pd.api.types.is_datetime64_any_dtype(ser):
            is_temporal = True
        elif pd.api.types.is_numeric_dtype(ser):
            try:
                num_ser = pd.to_numeric(ser, errors="coerce").dropna()
                if not num_ser.empty and (num_ser % 1 == 0).all() and (num_ser >= 1900).all() and (num_ser <= 2050).all():
                    is_temporal = True
            except Exception:
                pass
        else:
            # Check string date pattern or keywords (excluding entity/name columns)
            is_name_col = any(k in col_name_lower for k in ["name", "title", "artist", "user", "customer", "employee"])
            if not is_name_col:
                date_patterns = [r"^\d{4}$", r"^\d{4}[-/]\d{1,2}", r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", r"^q[1-4]"]
                sample_vals = [str(x).strip().lower() for x in ser.dropna().head(10)]
                if sample_vals and any(all(re.match(pat, v) for v in sample_vals) for pat in date_patterns):
                    is_temporal = True
                elif any(re.search(rf"(?:^|[_\s]){re.escape(k)}(?:$|[_\s])", col_name_lower) for k in ["date", "year", "month", "quarter", "ngay", "thang", "nam", "quy", "debut"]):
                    is_temporal = True

        if is_temporal:
            temporal_cols.append(col)
            if 2 <= n_unique <= 7:
                donut_pie_cat_cols.append(col)
            if 2 <= n_unique <= 25:
                valid_category_cols.append(col)
            continue

        # 2. Percentage / Ratio Metric Detection
        is_ratio = False
        if any(pct in col_name_lower for pct in ["%", "percent", "pct", "ratio", "rate", "share", "margin", "ty_le"]):
            is_ratio = True
        elif pd.api.types.is_numeric_dtype(ser):
            num_ser = pd.to_numeric(ser, errors="coerce").dropna()
            if not num_ser.empty and (num_ser >= 0).all() and (num_ser <= 1.0).all() and n_unique > 2:
                is_ratio = True

        if is_ratio:
            ratio_metrics.append(col)
            continue

        # 3. Numeric Continuous Metrics
        if pd.api.types.is_numeric_dtype(ser):
            if n_unique <= 7 and total_rows > 20:
                donut_pie_cat_cols.append(col)
                valid_category_cols.append(col)
            elif n_unique <= 20 and total_rows > 50:
                valid_category_cols.append(col)
            else:
                numeric_metrics.append(col)
        else:
            # 4. Text / Categorical Column
            unique_ratio = (n_unique / total_rows) if total_rows > 0 else 0
            if 2 <= n_unique <= 7:
                donut_pie_cat_cols.append(col)
            if 2 <= n_unique <= 25:
                valid_category_cols.append(col)
            else:
                high_cardinality_cols.append(col)

            # High-Cardinality Entity candidate (nunique >= 5, not a low-cardinality category)
            if n_unique >= 5:
                entity_cols.append(col)

    # Rank continuous metrics by standard deviation and total sum magnitude
    def metric_score(m: str) -> float:
        ser = pd.to_numeric(df[m], errors="coerce").fillna(0.0)
        tot = float(abs(ser).sum())
        std_val = float(ser.std()) if len(ser) > 1 else 0.0
        return tot + std_val

    numeric_metrics.sort(key=metric_score, reverse=True)

    # Rank entity candidates by unique cardinality (higher diversity represents primary entity)
    def entity_score(e: str) -> float:
        card = cardinality.get(str(e), 0)
        return float(card)

    entity_cols.sort(key=entity_score, reverse=True)

    if not entity_cols:
        entity_cols = high_cardinality_cols or [c for c in df.columns if c not in numeric_metrics] or [df.columns[0]]
    if not donut_pie_cat_cols:
        donut_pie_cat_cols = [c for c, cnt in cardinality.items() if 2 <= cnt <= 7 and c not in numeric_metrics]
        if not donut_pie_cat_cols:
            donut_pie_cat_cols = [c for c, cnt in cardinality.items() if 2 <= cnt <= 10]

    return {
        "total_rows": total_rows,
        "cardinality": cardinality,
        "temporal_cols": temporal_cols,
        "donut_pie_cat_cols": donut_pie_cat_cols,
        "valid_category_cols": valid_category_cols,
        "high_cardinality_cols": high_cardinality_cols,
        "numeric_metrics": numeric_metrics,
        "ratio_metrics": ratio_metrics,
        "entity_cols": entity_cols,
        "slicers": donut_pie_cat_cols[:3],
    }


def validate_and_correct_chart_specs(
    dashboard_spec: dict[str, Any],
    df_summary: dict[str, Any],
    df: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """Tự động tráo đổi hoặc sửa chart nếu LLM gán nhầm cột high-cardinality vào pie/donut.

    Đồng thời đảm bảo Bar Chart chính là biểu đồ xếp hạng Top Entity theo KPI chính.
    """
    if not isinstance(dashboard_spec, dict):
        return dashboard_spec

    charts = dashboard_spec.get("charts", [])
    if not isinstance(charts, list):
        return dashboard_spec

    cardinality = df_summary.get("cardinality", {})
    donut_candidates = df_summary.get("donut_pie_cat_cols", [])
    entity_cols = df_summary.get("entity_cols", [])
    numeric_metrics = df_summary.get("numeric_metrics", [])
    valid_cat_cols = df_summary.get("valid_category_cols", [])

    if df is None and "df" in df_summary and isinstance(df_summary["df"], pd.DataFrame):
        df = df_summary["df"]

    # Valid categorical column (nunique between 2 and 6)
    valid_cat_col = (
        donut_candidates[0] if donut_candidates
        else next((col for col, count in cardinality.items() if 2 <= count <= 6), None)
    )
    if not valid_cat_col and valid_cat_cols:
        valid_cat_col = valid_cat_cols[0]

    best_entity_col = entity_cols[0] if entity_cols else next((col for col, count in cardinality.items() if count >= 7), None)
    primary_metric = numeric_metrics[0] if numeric_metrics else None

    for chart in charts:
        if not isinstance(chart, dict):
            continue
        c_type = str(chart.get("type", "")).lower()
        dim = (
            chart.get("dimension")
            or chart.get("category_col")
            or chart.get("name_key")
            or chart.get("x_axis_key")
            or chart.get("xAxisKey")
        )

        # -------------------------------------------------------------
        # QUY TẮC A: Donut / Pie Chart (Tỷ Trọng & Thị Phần)
        # Bắt buộc: 2 <= nunique <= 6. Cấm nunique > 7 hoặc entity/ID
        # -------------------------------------------------------------
        if c_type in ["pie", "donut"]:
            dim_str = str(dim) if dim else ""
            unique_count = cardinality.get(dim_str, len(chart.get("data", [])))

            data_items = [d for d in chart.get("data", []) if isinstance(d, dict) and d.get("name") != "Khác"]
            if unique_count > 6 or len(data_items) > 6 or len(chart.get("data", [])) > 7 or (dim_str and dim_str in entity_cols and unique_count > 6):
                logger.warning(
                    "validate_and_correct_chart_specs: Correcting Pie/Donut chart '%s' (dim='%s', unique=%d) -> valid_cat_col='%s'",
                    chart.get("title"), dim_str, unique_count, valid_cat_col
                )
                if valid_cat_col:
                    chart["dimension"] = valid_cat_col
                    chart["name_key"] = "name"
                    chart["value_key"] = "value"
                    chart["avoidLabelOverlap"] = True
                    chart["minAngle"] = 5

                    # Metric Source Transparency & Safe Numeric Formatting
                    if primary_metric and df is not None and primary_metric in df.columns:
                        chart["measure"] = primary_metric
                        chart["aggregation"] = "SUM"
                        chart["title"] = f"Tỷ Trọng {primary_metric.replace('_', ' ').title()} theo {valid_cat_col.replace('_', ' ').title()}"
                        chart["subtitle"] = f"Phân bổ dựa trên cột '{primary_metric}' theo từng '{valid_cat_col}'"
                        try:
                            grp = df.groupby(valid_cat_col)[primary_metric].sum().sort_values(ascending=False)
                            top5 = grp.head(5)
                            other_sum = round(float(grp.iloc[5:].sum()), 2) if len(grp) > 5 else 0.0
                            new_data = [{"name": str(k), "value": round(float(v), 2)} for k, v in top5.items()]
                            if other_sum > 0:
                                new_data.append({"name": "Khác", "value": other_sum})
                            chart["data"] = new_data
                        except Exception:
                            vc = df[valid_cat_col].value_counts()
                            top5 = vc.head(5)
                            other_sum = int(vc.iloc[5:].sum()) if len(vc) > 5 else 0
                            new_data = [{"name": str(k), "value": int(v)} for k, v in top5.items()]
                            if other_sum > 0:
                                new_data.append({"name": "Khác", "value": other_sum})
                            chart["data"] = new_data
                    else:
                        chart["measure"] = "count"
                        chart["aggregation"] = "COUNT"
                        chart["title"] = f"Tỷ Trọng theo {valid_cat_col.replace('_', ' ').title()}"
                        chart["subtitle"] = f"Số lượng giao dịch (Đếm số dòng theo '{valid_cat_col}')"
                        if df is not None and valid_cat_col in df.columns:
                            vc = df[valid_cat_col].value_counts()
                            top5 = vc.head(5)
                            other_sum = int(vc.iloc[5:].sum()) if len(vc) > 5 else 0
                            new_data = [{"name": str(k), "value": int(v)} for k, v in top5.items()]
                            if other_sum > 0:
                                new_data.append({"name": "Khác", "value": other_sum})
                            chart["data"] = new_data
            else:
                # Ensure metadata exists for valid Pie/Donut
                if not chart.get("dimension") and dim_str:
                    chart["dimension"] = dim_str
                if not chart.get("measure"):
                    chart["measure"] = chart.get("value_key") or "count"
                if not chart.get("aggregation"):
                    chart["aggregation"] = "SUM" if chart.get("measure") and chart.get("measure") not in ["count", "value", "y"] else "COUNT"
                if not chart.get("subtitle"):
                    meas = chart.get("measure")
                    dim_label = chart.get("dimension") or dim_str
                    if meas and meas not in ["count", "value", "y"]:
                        chart["subtitle"] = f"Phân bổ dựa trên cột '{meas}' theo từng '{dim_label}'"
                    else:
                        chart["subtitle"] = f"Số lượng giao dịch (Đếm số dòng theo '{dim_label}')"

        # -------------------------------------------------------------
        # QUY TẮC B: Bar Chart chính (Biểu Đồ Phân Tích Chính)
        # Bắt buộc: Xếp hạng Top 10-15 Entity theo KPI liên tục.
        # Cấm: count(*) trên cột có cardinality <= 3 khi có entity & metrics.
        # -------------------------------------------------------------
        if c_type in ["bar", "ranking_bar"]:
            dim_str = str(dim) if dim else ""
            unique_count = cardinality.get(dim_str, len(chart.get("data", [])))

            if unique_count <= 3 and best_entity_col and best_entity_col != dim_str and primary_metric:
                logger.warning(
                    "validate_and_correct_chart_specs: Elevating Bar chart from low-cardinality '%s' to entity '%s' ranked by '%s'",
                    dim_str, best_entity_col, primary_metric
                )
                chart["dimension"] = best_entity_col
                chart["x_axis_key"] = "x"
                chart["y_axis_key"] = "y"
                chart["xAxisKey"] = "x"
                chart["yAxisKey"] = "y"
                chart["series_keys"] = ["y"]
                metric_label = primary_metric.replace("_", " ").title()
                entity_label = best_entity_col.replace("_", " ").title()
                chart["title"] = f"Top 15 {entity_label} Theo {metric_label}"

                if df is not None and best_entity_col in df.columns and primary_metric in df.columns:
                    grp = df.groupby(best_entity_col)[primary_metric].sum().sort_values(ascending=False).head(15).reset_index()
                    grp.columns = ["x", "y"]
                    chart["data"] = [{"x": str(r["x"]), "y": round(float(r["y"]), 2) if not pd.isna(r["y"]) else 0.0} for _, r in grp.iterrows()]
                    chart["x_data"] = [str(r["x"]) for _, r in grp.iterrows()]

    return dashboard_spec


def sanitize_json_value(val: Any) -> Any:
    """Ensure floating point NaNs and Infs are converted to valid JSON values."""
    if val is None:
        return None
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return val
    if isinstance(val, (int, str, bool)):
        return val
    if isinstance(val, dict):
        return {k: sanitize_json_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [sanitize_json_value(v) for v in val]
    return str(val)


class DataAnalystAgent(BaseAgent):
    """Multi-Agent Swarm Data Analyst Pipeline with PEV Self-Correction Loop."""

    def __init__(
        self,
        llm_client: LLMClient,
        model: str = "openai/gpt-4o-mini",
        mcp_client: Optional[Any] = None,
        redis_client: Optional[Any] = None,
    ) -> None:
        """Initialise DataAnalystAgent with unified LLM client."""
        self.llm_client: LLMClient = llm_client
        self.model: str = model
        self.mcp_client: Optional[Any] = mcp_client
        self.redis_client: Optional[Any] = redis_client
        self.sandbox: SafePythonSandbox = SafePythonSandbox(timeout_seconds=5.0)

    async def execute_sandbox_code(
        self,
        code: str,
        df: Optional[pd.DataFrame] = None,
    ) -> SandboxResult:
        """Safely execute custom statistical/regression Python code in isolated sandbox."""
        return await self.sandbox.execute_async(code=code, df=df)

    def get_metadata(self) -> dict[str, str]:
        """Return metadata describing this agent."""
        return {
            "name": "data_agent",
            "description": (
                "Multi-Agent Swarm Agent chuyên phân tích dữ liệu CSV/Excel, "
                "tính toán chỉ số KPI, tự quy hoạch layout 12 cột, sinh biểu đồ "
                "tương tác và nhận định chiến lược kinh doanh."
            ),
        }

    async def process_request(self, query: str, session_id: str) -> str:
        """Handle text-only request with automatic Redis session file context recovery."""
        logger.info(
            "DataAnalystAgent processing text-only request",
            extra={"session_id": session_id},
        )

        # 1. Attempt to recover active CSV file from Redis session state
        if self.redis_client is not None:
            try:
                active = await self.redis_client.get_active_file(session_id=session_id)
                if active and active.get("csv_content"):
                    logger.info(
                        "Restored active CSV file '%s' from Redis for session '%s'",
                        active.get("filename"),
                        session_id,
                        extra={"session_id": session_id},
                    )
                    return await self.process_csv_request(
                        query=query,
                        csv_content=active["csv_content"],
                        filename=active.get("filename", "active_dataset.csv"),
                        session_id=session_id,
                    )
            except Exception as exc:
                logger.warning(
                    "Redis active file recovery fallback: %s",
                    exc,
                    extra={"session_id": session_id},
                )

        # 2. Friendly fallback if no CSV context is available
        result: dict[str, str] = {
            "status": "success",
            "type": "text",
            "explanation": (
                "Để phân tích dữ liệu, vui lòng tải lên file CSV/Excel thông qua nút đính kèm tệp "
                "trên giao diện, sau đó nhập câu hỏi phân tích của bạn."
            ),
            "generated_code": "",
        }
        return json.dumps(result, ensure_ascii=False)

    async def process_csv_request(
        self,
        query: str,
        csv_content: str | bytes,
        filename: str,
        session_id: str,
    ) -> str:
        """Process CSV dataset via Multi-Agent Swarm Pipeline with PEV self-correction."""
        csv_size = len(csv_content) if isinstance(csv_content, bytes) else len(csv_content.encode("utf-8", errors="replace"))
        if csv_size > _MAX_CSV_BYTES:
            return json.dumps(
                {
                    "explanation": f"File '{filename}' quá lớn (giới hạn 10MB). Vui lòng giảm dung lượng file.",
                    "generated_code": "",
                },
                ensure_ascii=False,
            )

        # Save active file to Redis session state for follow-up context retention
        if self.redis_client is not None and csv_content:
            try:
                csv_str = csv_content if isinstance(csv_content, str) else csv_content.decode("utf-8", errors="replace")
                await self.redis_client.set_active_file(
                    session_id=session_id,
                    filename=filename,
                    csv_content=csv_str,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to cache active CSV in Redis: %s",
                    exc,
                    extra={"session_id": session_id},
                )

        # Parse CSV into Pandas DataFrame
        try:
            df: pd.DataFrame = safe_read_csv(csv_content)
        except Exception as exc:
            logger.error("Failed to parse CSV: %s", exc, extra={"session_id": session_id})
            return json.dumps(
                {
                    "explanation": f"Không thể đọc file '{filename}'. Vui lòng kiểm tra định dạng CSV.",
                    "generated_code": "",
                },
                ensure_ascii=False,
            )

        # -------------------------------------------------------------------
        # Intent Detection: TEXT_SUMMARY vs DASHBOARD_REQUEST
        # -------------------------------------------------------------------
        is_dashboard_req = self._is_dashboard_request(query)

        if not is_dashboard_req:
            logger.info(
                "Intent detected: TEXT_SUMMARY for query '%s'",
                query,
                extra={"session_id": session_id},
            )
            text_summary = await self._generate_text_summary(df, filename, query, session_id)
            return json.dumps(
                {
                    "status": "success",
                    "type": "text_summary",
                    "content": text_summary,
                    "explanation": text_summary,
                    "generated_code": "",
                    "metadata": {
                        "total_rows": len(df),
                        "total_cols": len(df.columns),
                        "columns": list(df.columns),
                        "file_name": filename,
                    },
                },
                ensure_ascii=False,
            )

        logger.info(
            "Intent detected: DASHBOARD_REQUEST for query '%s'",
            query,
            extra={"session_id": session_id},
        )

        # -------------------------------------------------------------------
        # Sub-Agent 1: Prompt Intent & Chart Requirement Parser
        # -------------------------------------------------------------------
        layout_type = self._detect_layout_type(query)

        chart_intent: dict[str, Any] = await self._parse_user_chart_intent(
            user_query=query,
            columns=df.columns.tolist(),
            session_id=session_id,
            df=df,
        )
        chart_intent["user_query"] = query
        chart_intent["layout_type"] = layout_type

        # -------------------------------------------------------------------
        # Sub-Agent 2: Analytical Data Executor
        # -------------------------------------------------------------------
        chart_data: dict[str, Any] = self._execute_data_aggregation(df, chart_intent)

        # -------------------------------------------------------------------
        # Sub-Agent 3: Dynamic Chart Spec Builder
        # -------------------------------------------------------------------
        primary_chart_spec: dict[str, Any] = self._build_custom_echarts_spec(chart_intent, chart_data)
        secondary_chart_spec: dict[str, Any] = self._build_secondary_chart_if_needed(df, chart_intent)

        # Base Data Analytics Exploration Data
        exploration_data: dict[str, Any] = self._run_data_exploration(df, filename, query)
        exploration_data["layout_type"] = layout_type
        exploration_data["primary_chart_spec"] = primary_chart_spec
        exploration_data["secondary_chart_spec"] = secondary_chart_spec
        exploration_data["chart_intent"] = chart_intent
        exploration_data["chart_data"] = chart_data

        # PEV Self-Correction Loop setup
        max_retries: int = _DEFAULT_MAX_RETRIES
        retry_count: int = 0
        error_feedback: list[str] = []
        verified: bool = False
        dashboard_ast: dict[str, Any] = {}
        story_text: str = ""

        while retry_count < max_retries:
            logger.info(
                "Swarm Pipeline Iteration %d/%d (feedback_count=%d)",
                retry_count + 1,
                max_retries,
                len(error_feedback),
                extra={"session_id": session_id},
            )

            # Sub-Agent 2: Dashboard Layout Architect (`_run_layout_architect`)
            layout_ast: dict[str, Any] = await self._run_layout_architect(
                exploration_data=exploration_data,
                query=query,
                session_id=session_id,
                error_feedback=error_feedback,
            )

            # Sub-Agent 3: Chart Spec Builder (`_run_chart_generator`)
            charts_spec: list[dict[str, Any]] = await self._run_chart_generator(
                exploration_data=exploration_data,
                layout_ast=layout_ast,
                session_id=session_id,
                error_feedback=error_feedback,
            )

            # Sub-Agent 4: Executive Storyteller (`_run_business_storyteller`)
            story_text = await self._run_business_storyteller(
                exploration_data=exploration_data,
                session_id=session_id,
            )

            # Assemble full Dashboard AST
            dashboard_ast = self._assemble_dashboard_ast(
                exploration_data=exploration_data,
                layout_ast=layout_ast,
                charts_spec=charts_spec,
                story_text=story_text,
                filename=filename,
                df=df,
            )

            # SUB-AGENT A: Chart & Data Validation Critic
            chart_valid, chart_feedback = self._evaluate_chart_data_quality(df, dashboard_ast)

            # SUB-AGENT B: Executive Storytelling Evaluator
            story_valid, story_feedback = await self._evaluate_storytelling_quality(df, dashboard_ast)

            # Base Structural Verifier
            verification_res: dict[str, Any] = self._verify_dashboard_quality(
                dashboard_ast=dashboard_ast,
                exploration_data=exploration_data,
            )
            base_verified = verification_res.get("is_verified", False)

            if chart_valid and story_valid and base_verified:
                logger.info(
                    "Dashboard AST quality verified successfully on iteration %d",
                    retry_count + 1,
                    extra={"session_id": session_id},
                )
                verified = True
                break

            retry_count += 1
            combined_feedback = f"Chart Issues: {chart_feedback} | Storytelling Issues: {story_feedback} | Base Issues: {verification_res.get('error_feedback')}"
            error_feedback.append(combined_feedback)
            logger.warning(
                "Quality Gate Retry %d/%d: %s",
                retry_count,
                max_retries,
                combined_feedback,
                extra={"session_id": session_id},
            )

            # Refine spec based on Reflection Swarm Loop Sub-Agents feedback
            dashboard_ast = await self._refine_dashboard_spec(df, dashboard_ast, combined_feedback)

        # Fallback auto-fix if verification did not reach 100% after max retries
        if not verified:
            logger.warning(
                "Max retries reached — applying Fallback Auto-Correction to Dashboard AST",
                extra={"session_id": session_id},
            )
            dashboard_ast = self._autofix_dashboard_ast(dashboard_ast, exploration_data)
            self._evaluate_chart_data_quality(df, dashboard_ast)
            verified = True

        pev_trace = {
            "retry_count": retry_count,
            "is_verified": verified,
            "error_feedback": error_feedback,
        }

        # Apply Heuristic Guardrail validate_and_correct_chart_specs before final output
        dashboard_ast = validate_and_correct_chart_specs(
            dashboard_ast,
            exploration_data,
            df,
        )

        # Ensure table.rows and totalRows metadata contain full dataset records
        dashboard_ast = self._enrich_spec_with_full_dataset(dashboard_ast, df)
        dashboard_ast["table"]["title"] = f"Bảng Chi Tiết Dữ Liệu ({filename})"

        # Sanitize entire output object for JSON serialization safety
        clean_dashboard_spec = sanitize_json_value(dashboard_ast)

        return json.dumps(
            {
                "status": "success",
                "type": "dashboard",
                "explanation": strip_emojis(clean_dashboard_spec.get("summaryText", story_text)),
                "dashboard_spec": clean_dashboard_spec,
                "generated_code": "",
                "pev_trace": pev_trace,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _is_dashboard_request(query: str) -> bool:
        """Classify user intent: DASHBOARD_REQUEST vs TEXT_SUMMARY."""
        query_lower = query.lower()

        # Negative override: explicit text/summary requests without dashboard
        negative_keywords = [
            "không cần biểu đồ",
            "không dựng dashboard",
            "không vẽ chart",
            "dạng văn bản",
            "chỉ tóm tắt",
            "dạng text",
            "tóm tắt văn bản",
        ]
        if any(neg in query_lower for neg in negative_keywords):
            return False

        dashboard_keywords = [
            "dashboard",
            "biểu đồ",
            "chart",
            "dựng báo cáo",
            "trực quan hóa",
            "vẽ",
        ]
        return any(kw in query_lower for kw in dashboard_keywords)

    async def _generate_text_summary(
        self,
        df: pd.DataFrame,
        filename: str,
        query: str,
        session_id: str,
    ) -> str:
        """Generate formatted Markdown text summary with Markdown tables for non-dashboard queries."""
        import numpy as np

        total_rows, total_cols = df.shape
        cols_info = []
        for col in df.columns:
            dtype_str = str(df[col].dtype)
            null_cnt = int(df[col].isnull().sum())
            cols_info.append(f"- `{col}` ({dtype_str}): {null_cnt} rỗng")

        # Descriptive statistics for numeric columns
        numeric_df = df.select_dtypes(include=[np.number])
        numeric_stats = {}
        if not numeric_df.empty:
            desc = numeric_df.describe().replace({np.nan: None}).to_dict()
            for col, stats in desc.items():
                numeric_stats[col] = {
                    "mean": round(stats.get("mean", 0) or 0, 2),
                    "std": round(stats.get("std", 0) or 0, 2),
                    "min": round(stats.get("min", 0) or 0, 2),
                    "50%": round(stats.get("50%", 0) or 0, 2),
                    "max": round(stats.get("max", 0) or 0, 2),
                }

        # Statistics for categorical columns
        cat_df = df.select_dtypes(exclude=[np.number])
        cat_stats = {}
        if not cat_df.empty:
            for col in cat_df.columns:
                val_counts = df[col].value_counts()
                top_val = str(val_counts.index[0]) if not val_counts.empty else "N/A"
                top_cnt = int(val_counts.iloc[0]) if not val_counts.empty else 0
                cat_stats[col] = {
                    "unique_count": int(df[col].nunique()),
                    "top_value": top_val,
                    "top_frequency": top_cnt,
                }

        prompt = (
            f"Bạn là Senior AI Data Analyst chuyên nghiệp.\n"
            f"Hãy trả lời câu hỏi của người dùng dựa trên tập dữ liệu CSV '{filename}'.\n\n"
            f"Câu hỏi người dùng: \"{query}\"\n\n"
            f"[THÔNG TIN THỐNG KÊ TẬP DỮ LIỆU]:\n"
            f"- Tên file: {filename}\n"
            f"- Số bản ghi (dòng): {total_rows:,}\n"
            f"- Số thuộc tính (cột): {total_cols}\n"
            f"- Chi tiết các cột:\n" + "\n".join(cols_info[:20]) + "\n\n"
            f"[THỐNG KÊ CÁC CỘT SỐ (NUMERIC METRICS)]:\n"
            f"{json.dumps(numeric_stats, ensure_ascii=False, indent=2)}\n\n"
            f"[THỐNG KÊ CÁC CỘT PHÂN LOẠI (CATEGORICAL METRICS)]:\n"
            f"{json.dumps(cat_stats, ensure_ascii=False, indent=2)}\n\n"
            f"YÊU CẦU TRÌNH BÀY NỘI DUNG:\n"
            f"1. Trả lời trực tiếp câu hỏi người dùng bằng tiếng Việt, rõ ràng, mạch lạc.\n"
            f"2. BẮT BUỘC sử dụng BẢNG MARKDOWN (Markdown Table) trình bày các số liệu thống kê (Dòng, Cột, Mean, Min, Max, Median,...).\n"
            f"3. CRITICAL FORMATTING RULE: Absolutely NEVER include any emojis (such as 📈, 🔍, 🎯, 📊, ⚠️, etc.) in titles or content. Output pure professional business Vietnamese text only.\n"
            f"4. Đưa ra nhận xét/tóm tắt ngắn gọn ở cuối câu trả lời.\n"
            f"5. TUYỆT ĐỐI KHÔNG sinh cấu trúc JSON DashboardSpec hay thẻ HTML.\n"
        )

        try:
            resp = await self.llm_client.chat_completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2048,
                session_id=session_id,
            )
            content = resp.choices[0].message.content or ""
            if content.strip():
                return strip_emojis(content.strip())
        except Exception as exc:
            logger.warning("LLM fallback for text summary: %s", exc, extra={"session_id": session_id})

        # Deterministic Markdown Fallback if LLM call fails
        summary_md = [
            f"### Tóm Tắt Dữ Liệu `{filename}`",
            "",
            "| Chỉ Số Tổng Quan | Giá Trị |",
            "| :--- | :--- |",
            f"| **Tổng số dòng (Rows)** | `{total_rows:,}` |",
            f"| **Tổng số cột (Columns)** | `{total_cols}` |",
            "",
            "#### Thống Kê Các Cột Số",
            "| Cột | Trung Bình (Mean) | Nhỏ Nhất (Min) | Trung Vị (Median) | Lớn Nhất (Max) |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for col, st in numeric_stats.items():
            summary_md.append(f"| `{col}` | {st['mean']} | {st['min']} | {st['50%']} | {st['max']} |")

        if cat_stats:
            summary_md.extend([
                "",
                "#### Thống Kê Các Cột Phân Loại",
                "| Cột | Số Giá Trị Khác Nhau | Giá Trị Xuất Hiện Nhiều Nhất | Tần Suất |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for col, st in cat_stats.items():
                summary_md.append(f"| `{col}` | {st['unique_count']} | `{st['top_value']}` | {st['top_frequency']} |")

        summary_md.extend([
            "",
            "**Nhận xét nhanh:** Tập dữ liệu có cấu trúc hoàn chỉnh với đầy đủ thông tin để tiến hành phân tích.",
        ])
        return strip_emojis("\n".join(summary_md))

    # ---------------------------------------------------------------------------
    # REFACTORED SUB-AGENTS SWARM PIPELINE IMPLEMENTATION
    # ---------------------------------------------------------------------------

    async def _parse_user_chart_intent(
        self, user_query: str, columns: list[str], session_id: str = "", df: Optional[pd.DataFrame] = None
    ) -> dict[str, Any]:
        """Sub-Agent 1: Prompt Intent & Chart Requirement Parser.

        Extracts target chart type, X-axis column + group type, Y-axis metric,
        aggregation method, and extra features (e.g. average line / trendline).
        """
        cols_str = ", ".join([f"'{c}'" for c in columns])
        prompt = (
            "Bạn là Sub-Agent Prompt Intent & Chart Requirement Parser.\n"
            "Nhiệm vụ: Trích xuất cấu trúc biểu đồ chính xác từ yêu cầu của người dùng.\n\n"
            f"Danh sách các cột sẵn có trong file dữ liệu: [{cols_str}]\n"
            f"Yêu cầu của người dùng: \"{user_query}\"\n\n"
            "CARDINALITY & CHART SELECTION RULES:\n"
            "1. 'donut' or 'pie' chart (Tỷ Trọng & Cơ Cấu):\n"
            "   - MUST select a low-cardinality categorical column (<Low_Cardinality_Categorical_Column>) with nunique between 2 and 7.\n"
            "   - NEVER use high-cardinality entity columns like names or IDs with nunique > 7.\n"
            "2. 'bar' chart (Ranking / Biểu Đồ Phân Tích Chính):\n"
            "   - MUST select the primary business entity column (<Primary_Entity_Column>) as the dimension and the primary continuous metric (<Primary_Numeric_Metric>) as the measure.\n"
            "   - Sort descending (Order By Metric DESC) and limit to Top 10 - 15 items.\n"
            "   - NEVER use Bar Chart just to count 2-3 categories when continuous business metrics exist.\n\n"
            "Hãy trích xuất và trả về JSON chuẩn theo schema sau (không thêm văn bản ngoài JSON):\n"
            "```json\n"
            "{\n"
            '  "primary_chart_type": "line|bar|pie|donut|scatter",\n'
            '  "x_axis": "tên_cột_cho_trục_x",\n'
            '  "group_by_type": "monthly|daily|yearly|categorical",\n'
            '  "y_axis_metric": "tên_cột_cho_trục_y",\n'
            '  "metric_label": "Nhãn_hiển_thị_tiếng_việt",\n'
            '  "aggregation": "sum|count|mean|median",\n'
            '  "extra_features": ["average_line", "trendline"],\n'
            '  "title": "Tiêu đề biểu đồ đề xuất"\n'
            "}\n"
            "```"
        )

        try:
            resp = await self.llm_client.chat_completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=512,
                session_id=session_id,
            )
            raw = resp.choices[0].message.content or ""
            match = re.search(r"```json\s*\n(.*?)```", raw, re.DOTALL)
            json_str = match.group(1).strip() if match else raw.strip()
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and "primary_chart_type" in parsed:
                # Ensure y_axis_metric is actually a continuous numeric column if df is provided
                if df is not None:
                    y_prop = str(parsed.get("y_axis_metric", ""))
                    if y_prop not in df.columns or not pd.api.types.is_numeric_dtype(df[y_prop]):
                        _, p_metric, _ = get_primary_metric_series(df)
                        if p_metric:
                            parsed["y_axis_metric"] = p_metric
                return parsed
        except Exception as exc:
            logger.warning("LLM Intent Parser fallback: %s", exc, extra={"session_id": session_id})

        query_lower = user_query.lower()
        cols_lower = {str(c).lower().strip(): c for c in columns}

        primary_type = "bar"
        extra_features = []
        if any(w in query_lower for w in ["line", "đường", "xu hướng", "trend", "thời gian", "theo tháng", "hàng tháng", "monthly"]):
            primary_type = "line"
        elif any(w in query_lower for w in ["tròn", "pie", "donut", "tỷ trọng", "tỷ lệ"]):
            primary_type = "pie"
        elif any(w in query_lower for w in ["scatter", "điểm"]):
            primary_type = "scatter"

        if any(w in query_lower for w in ["trung bình", "average", "mean", "benchmark"]):
            extra_features.append("average_line")
        if any(w in query_lower for w in ["trendline", "đường xu hướng"]):
            extra_features.append("trendline")

        classified = classify_columns_advanced(df) if df is not None else {}
        numeric_candidates = classified.get("numeric_metrics", [])
        entity_candidates = classified.get("entity_cols", [])
        donut_candidates = classified.get("donut_pie_cat_cols", [])

        x_col = None
        group_by = "categorical"
        date_keywords = ["date", "time", "month", "year", "day", "ngay", "thang", "nam", "order_date", "created_at"]
        for candidate_key, original_col in cols_lower.items():
            if any(k in candidate_key for k in date_keywords):
                x_col = original_col
                if any(w in query_lower for w in ["năm", "yearly", "year"]):
                    group_by = "yearly"
                elif any(w in query_lower for w in ["ngày", "daily"]):
                    group_by = "daily"
                else:
                    group_by = "monthly"
                break

        if not x_col:
            if primary_type in ["pie", "donut"]:
                x_col = donut_candidates[0] if donut_candidates else columns[0]
            else:
                x_col = entity_candidates[0] if entity_candidates else columns[0]

        y_col = None
        if numeric_candidates:
            y_col = numeric_candidates[0]
        elif df is not None:
            _, p_metric, _ = get_primary_metric_series(df)
            y_col = p_metric or columns[0]
        else:
            y_col = columns[0]

        return {
            "primary_chart_type": primary_type,
            "x_axis": x_col,
            "group_by_type": group_by,
            "y_axis_metric": y_col,
            "metric_label": str(y_col).replace("_", " ").title(),
            "aggregation": "sum",
            "extra_features": extra_features,
            "title": f"Phân Tích {str(y_col).replace('_', ' ').title()} Theo {str(x_col).replace('_', ' ').title()}",
        }

    @staticmethod
    def _detect_layout_type(query: str) -> str:
        """Classify dashboard layout mode: 'single_chart' vs 'full_dashboard'."""
        query_lower = query.lower()

        # Explicit full dashboard keywords
        dashboard_keywords = [
            "full_dashboard",
            "dashboard",
            "executive dashboard",
            "báo cáo tổng quan",
            "báo cáo quản trị",
            "tất cả biểu đồ",
            "nhiều biểu đồ",
            "toàn bộ",
        ]
        if any(dk in query_lower for dk in dashboard_keywords):
            return "full_dashboard"

        # Explicit single chart keywords
        single_keywords = [
            "single_chart",
            "single chart",
            "tạo biểu đồ",
            "vẽ biểu đồ",
            "biểu đồ đường",
            "biểu đồ cột",
            "biểu đồ tròn",
            "biểu đồ miền",
            "biểu đồ xu hướng",
            "1 biểu đồ",
            "một biểu đồ",
            "chỉ vẽ",
            "chỉ tạo",
        ]
        if any(sk in query_lower for sk in single_keywords):
            return "single_chart"

        return "full_dashboard"

    def _execute_data_aggregation(
        self, df: pd.DataFrame, intent: dict[str, Any]
    ) -> dict[str, Any]:
        """Sub-Agent 2: Analytical Data Executor.

        Runs Pandas/DuckDB logic to aggregate data series based on intent.
        Supports automatic datetime Groupby Month (YYYY-MM).
        """
        user_query = str(intent.get("user_query", "")).lower()
        x_col = intent.get("x_axis")
        y_col = intent.get("y_axis_metric")
        group_type = intent.get("group_by_type", "categorical")
        agg_func = intent.get("aggregation", "sum")
        extra_features = intent.get("extra_features", [])

        if "tháng" in user_query or "monthly" in user_query:
            group_type = "monthly"

        cols_map = {str(c).lower().strip(): c for c in df.columns}
        if x_col and str(x_col).lower().strip() in cols_map:
            x_col = cols_map[str(x_col).lower().strip()]
        else:
            x_col = df.columns[0]

        if y_col and str(y_col).lower().strip() in cols_map:
            actual_y = cols_map[str(y_col).lower().strip()]
            if pd.api.types.is_numeric_dtype(df[actual_y]):
                y_col = actual_y
            else:
                _, p_col, _ = get_primary_metric_series(df)
                y_col = p_col or actual_y
        else:
            _, p_col, _ = get_primary_metric_series(df)
            y_col = p_col or df.columns[0]

        work_df = df.copy()
        x_col_str = str(x_col)
        y_col_str = str(y_col)

        is_date = False
        date_target_col = None

        def is_numeric_year_column(ser: pd.Series) -> bool:
            try:
                num_ser = pd.to_numeric(ser, errors="coerce").dropna()
                if not num_ser.empty:
                    if (num_ser % 1 == 0).all() and (num_ser >= 1900).all() and (num_ser <= 2050).all():
                        return True
            except Exception:
                pass
            return False

        # Look for date column (e.g. order_date, date, created_at, ngay, thang)
        for candidate in [x_col_str] + list(df.columns):
            cand_lower = str(candidate).lower().strip()
            if any(k in cand_lower for k in ["date", "time", "month", "year", "ngay", "thang", "created_at"]):
                # If it's a numeric integer year column (e.g. Debut Year 2006, 2013), keep as categorical/int!
                if is_numeric_year_column(work_df[candidate]):
                    break

                try:
                    try:
                        parsed_ser = pd.to_datetime(work_df[candidate], errors="coerce", format="mixed")
                    except TypeError:
                        parsed_ser = pd.to_datetime(work_df[candidate], errors="coerce")
                    if parsed_ser.notnull().sum() > 0:
                        is_date = True
                        date_target_col = candidate
                        work_df["__parsed_date__"] = parsed_ser
                        work_df = work_df.dropna(subset=["__parsed_date__"])
                        break
                except Exception as exc:
                    logger.warning("Date parsing attempt failed for col %s: %s", candidate, exc)

        if is_date and date_target_col:
            x_col_str = str(date_target_col)
            if group_type == "yearly":
                work_df["group_x"] = work_df["__parsed_date__"].dt.to_period("Y").astype(str)
            elif group_type == "daily":
                work_df["group_x"] = work_df["__parsed_date__"].dt.to_period("D").astype(str)
            else:  # Monthly YYYY-MM
                work_df["group_x"] = work_df["__parsed_date__"].dt.strftime("%Y-%m")
        else:
            work_df["group_x"] = work_df[x_col_str].astype(str)

        work_df[y_col_str] = pd.to_numeric(work_df[y_col_str], errors="coerce").fillna(0.0)

        if agg_func == "mean":
            grp = work_df.groupby("group_x")[y_col_str].mean().reset_index()
        elif agg_func == "count":
            grp = work_df.groupby("group_x")[y_col_str].count().reset_index()
        elif agg_func == "median":
            grp = work_df.groupby("group_x")[y_col_str].median().reset_index()
        else:
            grp = work_df.groupby("group_x")[y_col_str].sum().reset_index()

        if is_date:
            grp = grp.sort_values("group_x", ascending=True)
        else:
            grp = grp.sort_values(y_col_str, ascending=False).head(15)

        x_values = [str(v) for v in grp["group_x"].tolist()]
        series_1 = [round(float(v), 2) for v in grp[y_col_str].tolist()]

        avg_val = round(float(pd.Series(series_1).mean()), 2) if series_1 else 0.0

        return {
            "x_col_name": x_col_str,
            "y_col_name": y_col_str,
            "is_date": is_date,
            "x_values": x_values,
            "series_1": series_1,
            "series_2": [],
            "average_val": avg_val,
            "total_sum": round(float(pd.Series(series_1).sum()), 2),
            "max_val": round(float(pd.Series(series_1).max()), 2) if series_1 else 0.0,
            "min_val": round(float(pd.Series(series_1).min()), 2) if series_1 else 0.0,
            "data_records": [
                {"x": x_val, "y": y_val}
                for x_val, y_val in zip(x_values, series_1)
            ],
        }

    def _build_custom_echarts_spec(
        self, intent: dict[str, Any], chart_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Sub-Agent 3: Dynamic Chart Spec Builder.

        Constructs ECharts specification matching 100% user prompt requirements
        with native ECharts markLine for Average Line.
        """
        primary_type = intent.get("primary_chart_type", "line")
        metric_label = intent.get("metric_label", "Chỉ Số")

        # Dynamic title based on actual X-axis data type
        if chart_data.get("is_date"):
            title = f"Xu Hướng {metric_label} Theo Tháng"
        else:
            x_title = str(chart_data["x_col_name"]).replace("_", " ").title()
            title = f"Xu Hướng {metric_label} Theo {x_title}"

        # Fix intent title if it clashes with date data (e.g. "danh mục sản phẩm" when data is YYYY-MM)
        intent_title = intent.get("title", "")
        if intent_title:
            intent_title_lower = intent_title.lower()
            if chart_data.get("is_date") and any(term in intent_title_lower for term in ["danh mục", "category", "phân loại"]):
                title = f"Xu Hướng {metric_label} Theo Tháng"
            else:
                title = intent_title

        y_col_lower = chart_data["y_col_name"].lower()
        is_monetary = any(
            k in y_col_lower for k in ["revenue", "price", "amount", "sales", "tien", "gia", "cost"]
        )

        primary_series = {
            "name": f"{metric_label}",
            "type": primary_type,
            "smooth": True,
            "symbolSize": 8,
            "data": chart_data["series_1"],
            "itemStyle": {"color": "#4F46E5"},
            "lineStyle": {"width": 3},
        }

        # Add native ECharts markLine for Average Line
        if chart_data.get("average_val") is not None:
            avg_val = chart_data["average_val"]
            primary_series["markLine"] = {
                "silent": True,
                "symbol": ["none", "none"],
                "label": {
                    "show": True,
                    "formatter": f"Mức Trung Bình: {avg_val:,.2f}" if not is_monetary else f"Mức Trung Bình: {avg_val:,.2f}",
                    "position": "end",
                    "fontSize": 11,
                    "fontWeight": "bold",
                    "color": "#EF4444",
                },
                "lineStyle": {
                    "type": "dashed",
                    "color": "#EF4444",
                    "width": 2,
                },
                "data": [{"type": "average", "name": "Trung Bình"}],
            }

        series_list = [primary_series]

        return {
            "chart_id": "primary_chart_custom",
            "type": primary_type,
            "title": title,
            "x_axis_key": "x",
            "y_axis_key": "y",
            "xAxisKey": "x",
            "yAxisKey": "y",
            "dimension": chart_data["x_col_name"],
            "metric": chart_data["y_col_name"],
            "measure": chart_data["y_col_name"],
            "measure_col": chart_data["y_col_name"],
            "x_data": chart_data["x_values"],
            "series": series_list,
            "data": chart_data["data_records"],
            "isMonetary": is_monetary,
            "unit": str(chart_data["y_col_name"]).replace("_", " ").title() if not is_monetary else "Đơn vị tiền tệ",
            "extra_features": intent.get("extra_features", []),
            "grid_span": 12 if intent.get("layout_type") == "single_chart" else 7,
            "average_val": chart_data.get("average_val"),
        }

    def _build_secondary_chart_if_needed(
        self, df: pd.DataFrame, intent: dict[str, Any]
    ) -> dict[str, Any]:
        """Sub-Agent 3 Fallback/Secondary Chart Builder.

        Generates a complementary Donut/Pie Chart based on low-cardinality categorical column (2 <= nunique <= 6).
        NEVER uses high-cardinality entity columns.
        """
        classified = classify_columns_advanced(df)
        donut_candidates = classified["donut_pie_cat_cols"]
        target_col = donut_candidates[0] if donut_candidates else (
            classified["valid_category_cols"][0] if classified["valid_category_cols"] else df.columns[0]
        )
        primary_metric = classified.get("numeric_metrics", [None])[0] if classified.get("numeric_metrics") else None
        if primary_metric and primary_metric in df.columns:
            try:
                grp = df.groupby(target_col)[primary_metric].sum().sort_values(ascending=False)
                top5 = grp.head(5)
                others_sum = round(float(grp.iloc[5:].sum()), 2) if len(grp) > 5 else 0.0
                pie_chart_data = [{"name": str(k), "value": round(float(v), 2)} for k, v in top5.items()]
                if others_sum > 0:
                    pie_chart_data.append({"name": "Khác", "value": others_sum})
                measure_val = primary_metric
                agg_val = "SUM"
                subtitle_val = f"Phân bổ dựa trên cột '{primary_metric}' theo từng '{target_col}'"
                title_val = f"Tỷ Trọng {primary_metric.replace('_', ' ').title()} theo {str(target_col).replace('_', ' ').title()}"
            except Exception:
                vc_pie = df[target_col].value_counts() if target_col in df.columns else pd.Series()
                top5 = vc_pie.head(5)
                others_sum = int(vc_pie.iloc[5:].sum()) if len(vc_pie) > 5 else 0
                pie_chart_data = [{"name": str(k), "value": int(v)} for k, v in top5.items()]
                if others_sum > 0:
                    pie_chart_data.append({"name": "Khác", "value": others_sum})
                measure_val = "count"
                agg_val = "COUNT"
                subtitle_val = f"Số lượng giao dịch (Đếm số dòng theo '{target_col}')"
                title_val = f"Tỷ Trọng Cơ Cấu Theo {str(target_col).replace('_', ' ').title()}"
        else:
            vc_pie = df[target_col].value_counts() if target_col in df.columns else pd.Series()
            top5 = vc_pie.head(5)
            others_sum = int(vc_pie.iloc[5:].sum()) if len(vc_pie) > 5 else 0
            pie_chart_data = [{"name": str(k), "value": int(v)} for k, v in top5.items()]
            if others_sum > 0:
                pie_chart_data.append({"name": "Khác", "value": others_sum})
            measure_val = "count"
            agg_val = "COUNT"
            subtitle_val = f"Số lượng giao dịch (Đếm số dòng theo '{target_col}')"
            title_val = f"Tỷ Trọng Cơ Cấu Theo {str(target_col).replace('_', ' ').title()}"

        return {
            "chart_id": "chart_pie_composition",
            "type": "donut",
            "title": title_val,
            "subtitle": subtitle_val,
            "name_key": "name",
            "value_key": "value",
            "dimension": str(target_col),
            "measure": measure_val,
            "aggregation": agg_val,
            "data": pie_chart_data,
            "grid_span": 5,
        }

    def _run_data_exploration(
        self, df: pd.DataFrame, filename: str, query: str
    ) -> dict[str, Any]:
        """Sub-Agent 1: Data Analytics Executor.

        Uses Pandas/DuckDB logic to compute shape, column classifications, KPIs,
        group-by aggregations, and table preview records.
        """
        total_rows = len(df)
        total_cols = len(df.columns)

        classified = classify_columns_advanced(df)
        valid_cat_cols = classified["valid_category_cols"]
        numeric_metrics = classified["numeric_metrics"]
        high_card_cols = classified["high_cardinality_cols"]

        cols_lower = [str(c).lower() for c in df.columns]
        monetary_keywords = ["price", "cost", "amount", "revenue", "salary", "fee", "sales", "tien", "gia"]
        has_sales = any(any(k in c for k in monetary_keywords) for c in cols_lower)

        # Calculate exact revenue series using domain rules
        rev_series = get_revenue_series(df)
        calculated_revenue = float(rev_series.sum()) if not rev_series.empty else None

        # Build Executive KPI Cards (Top 3-4 Cards, purely data-driven)
        kpi_cards = []
        kpi_cards.append(
            {
                "id": "kpi_total_records",
                "title": "TỔNG SỐ BẢN GHI",
                "value": f"{total_rows:,}",
                "unit": "Hàng",
                "type": "count",
                "subtitle": f"{total_rows:,} bản ghi",
                "icon": "Database",
            }
        )

        # Primary Continuous Metric Sum & Average
        if numeric_metrics:
            p_col = numeric_metrics[0]
            p_ser = pd.to_numeric(df[p_col], errors="coerce").dropna()
            if not p_ser.empty:
                total_val = float(p_ser.sum())
                avg_val = float(p_ser.mean())
                p_label = str(p_col).replace("_", " ").upper()
                p_unit = str(p_col).replace("_", " ").title()
                is_monetary = any(k in str(p_col).lower() for k in ["price", "cost", "revenue", "salary", "tien", "gia", "usd", "amount", "sales"])
                p_type = "currency" if is_monetary else "number"
                kpi_cards.append(
                    {
                        "id": f"kpi_total_{p_col}",
                        "title": f"TỔNG {p_label}",
                        "value": f"{total_val:,.2f}" if (total_val % 1 != 0) else f"{total_val:,.0f}",
                        "unit": p_unit,
                        "type": p_type,
                        "subtitle": "Quy mô tổng hợp",
                        "icon": "TrendingUp",
                    }
                )
                kpi_cards.append(
                    {
                        "id": f"kpi_avg_{p_col}",
                        "title": f"TRUNG BÌNH {p_label}",
                        "value": f"{avg_val:,.2f}" if (avg_val % 1 != 0) else f"{avg_val:,.0f}",
                        "unit": p_unit,
                        "type": p_type,
                        "subtitle": "Bình quân mỗi bản ghi",
                        "icon": "TrendingUp",
                    }
                )

        # Distinct Entity Count
        entity_candidates = classified.get("entity_cols", [])
        if entity_candidates and len(kpi_cards) < 4:
            e_col = entity_candidates[0]
            e_uniq = df[e_col].nunique()
            e_label = str(e_col).replace("_", " ").upper()
            kpi_cards.append(
                {
                    "id": f"kpi_uniq_{e_col}",
                    "title": f"TỔNG SỐ {e_label}",
                    "value": f"{e_uniq:,}",
                    "unit": "Thực thể",
                    "type": "count",
                    "subtitle": f"Số lượng {str(e_col).replace('_', ' ')} khác nhau",
                    "icon": "Layers",
                }
            )

        # Secondary Continuous Metric fallback
        if len(kpi_cards) < 4 and len(numeric_metrics) > 1:
            s_col = numeric_metrics[1]
            s_ser = pd.to_numeric(df[s_col], errors="coerce").dropna()
            if not s_ser.empty:
                s_total = float(s_ser.sum())
                s_label = str(s_col).replace("_", " ").upper()
                s_unit = str(s_col).replace("_", " ").title()
                s_is_monetary = any(k in str(s_col).lower() for k in ["price", "cost", "revenue", "salary", "tien", "gia", "usd", "amount", "sales"])
                kpi_cards.append(
                    {
                        "id": f"kpi_num_{s_col}",
                        "title": f"TỔNG {s_label}",
                        "value": f"{s_total:,.2f}" if (s_total % 1 != 0) else f"{s_total:,.0f}",
                        "unit": s_unit,
                        "type": "currency" if s_is_monetary else "number",
                        "subtitle": "Chỉ số bổ trợ",
                        "icon": "Hash",
                    }
                )

        # Compute Bar Group-By aggregation data (Ranking Bar: Top Entity by Primary Continuous KPI)
        entity_candidates = classified.get("entity_cols", [])
        target_bar_col = entity_candidates[0] if entity_candidates else (
            high_card_cols[0] if high_card_cols else (valid_cat_cols[0] if valid_cat_cols else df.columns[0])
        )

        primary_metric = numeric_metrics[0] if numeric_metrics else None

        bar_chart_data = []
        is_bar_monetary = False
        if target_bar_col in df.columns:
            if primary_metric and primary_metric in df.columns:
                grp = df.groupby(target_bar_col)[primary_metric].sum().sort_values(ascending=False).head(15).reset_index()
                grp.columns = ["x", "y"]
                bar_chart_data = [{"x": str(row["x"]), "y": round(float(row["y"]), 2) if not pd.isna(row["y"]) else 0.0} for _, row in grp.iterrows()]
                is_bar_monetary = any(k in str(primary_metric).lower() for k in ["revenue", "price", "amount", "sales", "tien", "gia", "cost"])
            else:
                vc = df[target_bar_col].value_counts().head(15).reset_index()
                vc.columns = ["x", "y"]
                bar_chart_data = [{"x": str(row["x"]), "y": int(row["y"]) if not pd.isna(row["y"]) else 0} for _, row in vc.iterrows()]
                is_bar_monetary = False

        # Compute Pie Group-By aggregation data (STRICT CARDINALITY: 2 <= nunique <= 6)
        donut_candidates = classified.get("donut_pie_cat_cols", [])
        target_pie_col = donut_candidates[0] if donut_candidates else (
            valid_cat_cols[0] if valid_cat_cols else df.columns[0]
        )
        pie_chart_data = []
        if target_pie_col in df.columns:
            vc_pie = df[target_pie_col].value_counts()
            top5 = vc_pie.head(5)
            others_sum = int(vc_pie.iloc[5:].sum()) if len(vc_pie) > 5 else 0
            pie_chart_data = [{"name": str(k), "value": int(v)} for k, v in top5.items()]
            if others_sum > 0:
                pie_chart_data.append({"name": "Khác", "value": others_sum})

        # AG Grid Columns and Clean Table Rows (Safe NaN/Inf replacement up to 5,000 rows)
        import numpy as np
        cleaned_df = df.head(5000).replace({np.nan: None, np.inf: None, -np.inf: None}).fillna("")
        table_rows = json.loads(cleaned_df.to_json(orient="records"))
        table_cols = [
            {
                "field": str(col),
                "headerName": str(col).replace("_", " ").title(),
                "sortable": True,
                "filter": True,
            }
            for col in df.columns
        ]

        return {
            "filename": filename,
            "query": query,
            "total_rows": total_rows,
            "total_cols": total_cols,
            "has_sales": has_sales,
            "valid_category_cols": valid_cat_cols,
            "numeric_metrics": numeric_metrics,
            "high_cardinality_cols": high_card_cols,
            "cardinality": classified["cardinality"],
            "donut_pie_cat_cols": classified["donut_pie_cat_cols"],
            "entity_cols": classified["entity_cols"],
            "slicers": classified.get("slicers", []),
            "primary_metric_name": str(primary_metric) if primary_metric else "",
            "df": df,
            "kpi_cards": kpi_cards,
            "bar_chart_data": bar_chart_data,
            "target_bar_col": str(target_bar_col),
            "is_bar_monetary": is_bar_monetary,
            "pie_chart_data": pie_chart_data,
            "target_pie_col": str(target_pie_col),
            "table_cols": table_cols,
            "table_cols_names": list(df.columns),
            "table_rows": table_rows,
        }

    async def _run_layout_architect(
        self,
        exploration_data: dict[str, Any],
        query: str,
        session_id: str,
        error_feedback: list[str],
    ) -> dict[str, Any]:
        """Sub-Agent 2: Dashboard Layout Architect.

        Plans skeleton layout based on 12-column grid system (`col-span-12`,
        `col-span-7`, `col-span-5`). Adjusts based on Verifier error feedback.
        """
        feedback_prompt = ""
        if error_feedback:
            feedback_prompt = f"\n\n[LỖI CẦN SỬA TỪ VÒNG KIỂM ĐỊNH TRƯỚC]:\n- " + "\n- ".join(error_feedback)

        prompt = (
            f"Bạn là Sub-Agent Dashboard Layout Architect chuyên quy hoạch hệ thống Grid 12 cột.\n"
            f"Dữ liệu dataset: {exploration_data['total_rows']} dòng × {exploration_data['total_cols']} cột.\n"
            f"Danh sách các cột THỰC TẾ CÓ TRONG DATASET: {exploration_data.get('table_cols_names', [])}\n"
            f"Yêu cầu người dùng: {query}\n"
            f"{feedback_prompt}\n\n"
            f"QUY TẮC GRID 12 CỘT & SCHEMA NGHIÊM NGẶT:\n"
            f"1. Tổng `col_span` của tất cả ô trong 1 hàng (Row) BẮT BUỘC PHẢI BẰNG 12 (Ví dụ: 7 + 5 = 12 hoặc 3 + 3 + 3 + 3 = 12).\n"
            f"2. Hàng 1: Hàng KPI Cards (`type`: 'kpi_grid', `col_span`: 12).\n"
            f"3. Hàng 2: Hàng Biểu Đồ (`type`: 'chart_grid', `col_span`: 12, bao gồm ô 1 `col_span`: 7 và ô 2 `col_span`: 5).\n"
            f"4. Hàng 3: Hàng Bảng Chi Tiết (`type`: 'data_table', `col_span`: 12).\n"
            f"5. BẮT BUỘC CHỈ sử dụng tên cột THỰC TẾ có trong dataset. TUYỆT ĐỐI KHÔNG tự bịa tên cột không tồn tại nếu không có trong dataset.\n\n"
            f"CARDINALITY & CHART SELECTION RULES:\n"
            f"1. 'donut' or 'pie' chart (Composition / Proportion):\n"
            f"   - MUST select a low-cardinality categorical column (<Low_Cardinality_Categorical_Column>) with nunique between 2 and 7 (e.g. from {exploration_data.get('donut_pie_cat_cols', [])}).\n"
            f"   - NEVER use high-cardinality entity columns like names or IDs with nunique > 7.\n"
            f"2. 'bar' chart (Ranking / Main Analysis):\n"
            f"   - MUST select the primary business entity column (<Primary_Entity_Column>, e.g. from {exploration_data.get('entity_cols', [])[:3]}) as the dimension and the primary continuous metric (<Primary_Numeric_Metric>, e.g. from {exploration_data.get('numeric_metrics', [])[:3]}) as the measure.\n"
            f"   - Sort descending (Order By Metric DESC) and limit to Top 10 - 15 items.\n"
            f"   - NEVER use Bar Chart just to count 2-3 categories when continuous business metrics exist.\n\n"
            f"Xuất ra định dạng JSON duy nhất:\n"
            f"```json\n"
            f"{{\n"
            f'  "grid_columns": 12,\n'
            f'  "rows": [\n'
            f'    {{\n'
            f'      "row_id": "row_kpis",\n'
            f'      "col_span": 12,\n'
            f'      "type": "kpi_grid",\n'
            f'      "items": [\n'
            f'        {{"id": "kpi_1", "col_span": 3}},\n'
            f'        {{"id": "kpi_2", "col_span": 3}},\n'
            f'        {{"id": "kpi_3", "col_span": 3}},\n'
            f'        {{"id": "kpi_4", "col_span": 3}}\n'
            f"      ]\n"
            f"    }},\n"
            f"    {{\n"
            f'      "row_id": "row_charts",\n'
            f'      "col_span": 12,\n'
            f'      "type": "chart_grid",\n'
            f'      "items": [\n'
            f'        {{"chart_id": "bar_main", "type": "bar", "col_span": 7}},\n'
            f'        {{"chart_id": "pie_proportion", "type": "pie", "col_span": 5}}\n'
            f"      ]\n"
            f"    }},\n"
            f"    {{\n"
            f'      "row_id": "row_table",\n'
            f'      "col_span": 12,\n'
            f'      "type": "data_table",\n'
            f'      "items": [{{"table_id": "main_table", "col_span": 12}}]\n'
            f"    }}\n"
            f"  ]\n"
            f"}}\n"
            f"```"
        )

        try:
            resp = await self.llm_client.chat_completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1024,
                session_id=session_id,
            )
            raw = resp.choices[0].message.content or ""
            match = re.search(r"```json\s*\n(.*?)```", raw, re.DOTALL)
            if match:
                return json.loads(match.group(1).strip())
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Sub-Agent 2 Layout Architect LLM fallback: %s", exc, extra={"session_id": session_id})

        # Fallback Standard 12-col layout
        return {
            "grid_columns": 12,
            "rows": [
                {
                    "row_id": "row_kpis",
                    "col_span": 12,
                    "type": "kpi_grid",
                    "items": [
                        {"id": "kpi_1", "col_span": 3},
                        {"id": "kpi_2", "col_span": 3},
                        {"id": "kpi_3", "col_span": 3},
                        {"id": "kpi_4", "col_span": 3},
                    ],
                },
                {
                    "row_id": "row_charts",
                    "col_span": 12,
                    "type": "chart_grid",
                    "items": [
                        {"chart_id": "bar_main", "type": "bar", "col_span": 7},
                        {"chart_id": "pie_proportion", "type": "pie", "col_span": 5},
                    ],
                },
                {
                    "row_id": "row_table",
                    "col_span": 12,
                    "type": "data_table",
                    "items": [{"table_id": "main_table", "col_span": 12}],
                },
            ],
        }

    async def _run_chart_generator(
        self,
        exploration_data: dict[str, Any],
        layout_ast: dict[str, Any],
        session_id: str,
        error_feedback: list[str],
    ) -> list[dict[str, Any]]:
        """Sub-Agent 3: Chart Spec Builder.

        Generates ECharts specs matching 100% user prompt requirements.
        """
        if exploration_data.get("primary_chart_spec"):
            p_spec = exploration_data["primary_chart_spec"]
            if exploration_data.get("layout_type") == "single_chart":
                res = [p_spec]
            else:
                s_spec = exploration_data.get("secondary_chart_spec") or {
                    "chart_id": "secondary_chart_proportion",
                    "type": "pie",
                    "title": f"Tỷ Trọng Cơ Cấu Theo {exploration_data.get('target_pie_col', 'Phân Loại').replace('_', ' ').title()}",
                    "name_key": "name",
                    "value_key": "value",
                    "dimension": exploration_data.get("target_pie_col"),
                    "data": exploration_data.get("pie_chart_data", []),
                    "grid_span": 5,
                }
                res = [p_spec, s_spec]
            validated = validate_and_correct_chart_specs({"charts": res}, exploration_data, exploration_data.get("df"))
            return validated.get("charts", res)

        # Standard Fallback Chart Specs
        bar_col_title = exploration_data["target_bar_col"].replace("_", " ").title()
        primary_metric_title = exploration_data.get("primary_metric_name", "").replace("_", " ").title()
        is_monetary = exploration_data["is_bar_monetary"]
        chart_title = (
            f"Top 15 {bar_col_title} Theo {primary_metric_title}"
            if primary_metric_title
            else f"Top 15 {bar_col_title} Xếp Hạng"
        )

        bar_spec = {
            "chart_id": f"bar_{exploration_data['target_bar_col']}",
            "type": "bar",
            "title": chart_title,
            "x_axis_key": "x",
            "y_axis_key": "y",
            "xAxisKey": "x",
            "yAxisKey": "y",
            "series_keys": ["y"],
            "dimension": exploration_data["target_bar_col"],
            "metric": exploration_data.get("primary_metric_name"),
            "measure": exploration_data.get("primary_metric_name"),
            "measure_col": exploration_data.get("primary_metric_name"),
            "isMonetary": is_monetary,
            "unit": str(exploration_data.get("primary_metric_name", "")).replace("_", " ").title() if is_monetary else "Đơn vị",
            "data": exploration_data["bar_chart_data"],
            "grid_span": 12 if exploration_data.get("layout_type") == "single_chart" else 7,
        }

        if exploration_data.get("layout_type") == "single_chart":
            return [bar_spec]

        pie_col_title = exploration_data["target_pie_col"].replace("_", " ").title()
        primary_metric = exploration_data.get("primary_metric_name")
        if primary_metric:
            pie_measure = primary_metric
            pie_agg = "SUM"
            pie_subtitle = f"Phân bổ dựa trên cột '{primary_metric}' theo từng '{exploration_data['target_pie_col']}'"
            pie_title = f"Tỷ Trọng {primary_metric.replace('_', ' ').title()} theo {pie_col_title}"
        else:
            pie_measure = "count"
            pie_agg = "COUNT"
            pie_subtitle = f"Số lượng giao dịch (Đếm số dòng theo '{exploration_data['target_pie_col']}')"
            pie_title = f"Tỷ Trọng theo {pie_col_title}"

        pie_spec = {
            "chart_id": "chart_pie_composition",
            "type": "donut",
            "title": pie_title,
            "subtitle": pie_subtitle,
            "name_key": "name",
            "value_key": "value",
            "dimension": exploration_data["target_pie_col"],
            "measure": pie_measure,
            "aggregation": pie_agg,
            "data": exploration_data["pie_chart_data"],
            "grid_span": 5,
        }
        res = [bar_spec, pie_spec]
        validated = validate_and_correct_chart_specs({"charts": res}, exploration_data, exploration_data.get("df"))
        return validated.get("charts", res)

    async def _run_business_storyteller(
        self, exploration_data: dict[str, Any], session_id: str
    ) -> str:
        """Sub-Agent 4: Executive Storyteller.

        Synthesizes 3 business blocks: Diễn Biến -> Nguyên Nhân -> Khuyến Nghị based on exact chart data.
        """
        chart_data = exploration_data.get("chart_data")
        chart_intent = exploration_data.get("chart_intent")

        if chart_data and chart_intent:
            summary_payload = {
                "title": chart_intent.get("title"),
                "primary_chart_type": chart_intent.get("primary_chart_type"),
                "x_col": chart_data.get("x_col_name"),
                "y_col": chart_data.get("y_col_name"),
                "total_sum": chart_data.get("total_sum"),
                "average_val": chart_data.get("average_val"),
                "max_val": chart_data.get("max_val"),
                "min_val": chart_data.get("min_val"),
                "data_preview": chart_data.get("data_records", [])[:6],
            }
        else:
            summary_payload = {
                "total_rows": exploration_data["total_rows"],
                "total_cols": exploration_data["total_cols"],
                "has_sales": exploration_data["has_sales"],
                "kpis": exploration_data["kpi_cards"],
                "bar_top_data": exploration_data["bar_chart_data"][:3],
                "pie_top_data": exploration_data["pie_chart_data"][:3],
            }

        prompt = (
            "Bạn là Sub-Agent Executive Storyteller. Nhiệm vụ của bạn là viết 3 câu tóm tắt nhận định kinh doanh giải thích ĐÚNG XU HƯỚNG CỦA BIỂU ĐỒ NÀY dựa TRÊN 100% SỐ LIỆU THỰC TẾ TRONG JSON.\n\n"
            f"Dữ liệu tổng hợp:\n{json.dumps(summary_payload, ensure_ascii=False)}\n\n"
            "QUY TẮC NGHIÊM NGẶT:\n"
            "1. Chỉ ra điểm đỉnh/đáy của xu hướng hoặc giá trị vượt/giảm so với mức trung bình.\n"
            "2. Mọi con số phải trích dẫn chính xác từ JSON.\n"
            "3. CRITICAL FORMATTING RULE: Absolutely NEVER include any emojis (such as 📈, 🔍, 🎯, 📊, ⚠️, etc.) in the titles, subtitle badges, or body text of the executive analysis. Output pure professional business Vietnamese text only.\n"
            "4. Trả về đúng 3 dòng định dạng:\n"
            "Diễn biến: ...\n"
            "Nguyên nhân: ...\n"
            "Khuyến nghị: ...\n"
        )

        try:
            resp = await self.llm_client.chat_completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1024,
                session_id=session_id,
            )
            text = resp.choices[0].message.content or ""
            if "Diễn biến" in text and "Nguyên nhân" in text:
                return strip_emojis(text.strip())
        except Exception as exc:
            logger.warning("Sub-Agent 4 Storyteller LLM fallback: %s", exc, extra={"session_id": session_id})

        # Deterministic Fallback Story
        if chart_data:
            avg_v = chart_data.get("average_val", 0)
            max_v = chart_data.get("max_val", 0)
            return strip_emojis(
                f"Diễn biến: Xu hướng `{chart_data.get('y_col_name')}` ghi nhận mức cao nhất tại {max_v:,.2f} và đạt mức trung bình toàn kỳ là {avg_v:,.2f}.\n"
                f"Nguyên nhân: Biến động xu hướng phản ánh sự tập trung ở các giai đoạn cao điểm vượt ngưỡng benchmark.\n"
                f"Khuyến nghị: Tập trung duy trì đà tăng trưởng tại các giai đoạn đỉnh điểm và tối ưu chi phí vận hành ở các chu kỳ giảm."
            )
        rows_cnt = exploration_data["total_rows"]
        cols_cnt = exploration_data["total_cols"]
        top_cat = exploration_data["bar_chart_data"][0]["x"] if exploration_data["bar_chart_data"] else "N/A"
        return strip_emojis(
            f"Diễn biến: Tập dữ liệu ghi nhận tổng cộng {rows_cnt:,} bản ghi với {cols_cnt} thuộc tính phân tích chính.\n"
            f"Nguyên nhân: Phân nhóm `{top_cat}` đóng góp tỷ trọng cao nhất trong các chỉ số nhóm chính.\n"
            f"Khuyến nghị: Tập trung theo dõi diễn biến của phân nhóm chủ lực và duy trì giám sát các số liệu bất thường."
        )

    def _verify_dashboard_quality(
        self, dashboard_ast: dict[str, Any], exploration_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Sub-Agent 5: Verifier & Evaluator Node.

        Validates 12-col layout width, checks for NaN/undefined/null, and ensures key mapping integrity.
        """
        error_feedback: list[str] = []

        # 1. Check Layout Grid Width
        layout = dashboard_ast.get("layout", {})
        rows = layout.get("rows", [])
        if not rows:
            error_feedback.append("Layout AST thiếu danh sách hàng (rows).")
        else:
            for row in rows:
                row_span = row.get("col_span", 12)
                if row_span != 12:
                    error_feedback.append(f"Hàng `{row.get('row_id')}` có col_span = {row_span} khác 12.")

                items = row.get("items", [])
                if len(items) > 1:
                    items_sum = sum(item.get("col_span", 0) for item in items)
                    if items_sum != 12:
                        error_feedback.append(
                            f"Tổng col_span của các ô trong hàng `{row.get('row_id')}` = {items_sum} khác 12."
                        )

        # 2. Check Chart Specs & Data Values
        charts = dashboard_ast.get("charts", [])
        if not charts:
            error_feedback.append("Danh sách biểu đồ (charts) đang bị rỗng.")
        else:
            for idx, chart in enumerate(charts):
                c_title = chart.get("title", f"Chart {idx+1}")
                c_data = chart.get("data", [])
                if not c_data or len(c_data) == 0:
                    error_feedback.append(f"Biểu đồ '{c_title}' có mảng dữ liệu data = [] (rỗng).")
                    continue

                # Check for NaN / undefined / null
                for row in c_data:
                    for k, v in row.items():
                        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                            error_feedback.append(f"Biểu đồ '{c_title}' chứa giá trị invalid (NaN/None) tại key '{k}'.")

                # Key mapping check
                c_type = chart.get("type", "bar")
                first_row = c_data[0]
                if c_type in ["bar", "line"]:
                    x_key = chart.get("x_axis_key") or chart.get("xAxisKey")
                    y_key = chart.get("y_axis_key") or chart.get("yAxisKey")
                    if not x_key or x_key not in first_row:
                        error_feedback.append(f"Biểu đồ '{c_title}' thiếu key X-axis '{x_key}' trong data.")
                    if not y_key or y_key not in first_row:
                        error_feedback.append(f"Biểu đồ '{c_title}' thiếu key Y-axis '{y_key}' trong data.")
                elif c_type in ["pie", "donut"]:
                    n_key = chart.get("name_key", "name")
                    v_key = chart.get("value_key", "value")
                    if n_key not in first_row:
                        error_feedback.append(f"Biểu đồ tròn '{c_title}' thiếu name_key '{n_key}' trong data.")
                    if v_key not in first_row:
                        error_feedback.append(f"Biểu đồ tròn '{c_title}' thiếu value_key '{v_key}' trong data.")
                    dim = chart.get("dimension") or chart.get("category_col") or n_key
                    cardinality_map = exploration_data.get("cardinality", {})
                    dim_str = str(dim) if dim else ""
                    uniq = cardinality_map.get(dim_str, len(c_data))
                    non_other = [d for d in c_data if isinstance(d, dict) and d.get("name") != "Khác"]
                    if uniq > 7 or len(c_data) > 7 or len(non_other) > 6:
                        error_feedback.append(
                            "Lỗi nghiêm trọng: Donut chart đang nhận cột có độ đa dạng quá lớn làm vỡ biểu đồ ('Khác: 99%'). "
                            "Hãy đổi Donut chart sang nhóm phân loại hẹp (<Low_Cardinality_Category> có nunique 2-7) và gán thực thể chính vào Bar Chart."
                        )

        # 3. Check KPIs & Summary completeness
        kpis = dashboard_ast.get("kpiCards", [])
        if not kpis:
            error_feedback.append("Thiếu danh sách thẻ KPI (kpiCards).")

        summary = dashboard_ast.get("summaryText", "")
        if not summary or len(summary.strip()) == 0:
            error_feedback.append("Nội dung nhận định (summaryText) bị rỗng.")

        is_verified = len(error_feedback) == 0
        return {
            "is_verified": is_verified,
            "error_feedback": error_feedback,
        }

    def _evaluate_chart_data_quality(
        self, df: pd.DataFrame, spec: dict[str, Any]
    ) -> tuple[bool, str]:
        """Sub-Agent A: Chart & Data Validation Critic.

        Validates date parsing integrity (Epoch Date 1970-01 prevention),
        enforces Pie/Donut anti-overlap settings, and guarantees complete
        key metric mapping across Frontend spec properties.
        """
        issues: list[str] = []

        # 1. Normalize key metrics for Frontend compatibility
        total_rows = len(df)
        total_cols = len(df.columns)
        spec["totalRows"] = total_rows
        spec["totalColumns"] = total_cols
        spec["total_rows"] = total_rows
        spec["total_cols"] = total_cols
        spec["total_records"] = total_rows
        spec["total_fields"] = total_cols

        # 2. Check for Epoch Date Bug ("1970-01") in charts data
        for idx, chart in enumerate(spec.get("charts", [])):
            c_title = chart.get("title", f"Chart {idx+1}")
            x_data = chart.get("x_data", []) or chart.get("xAxis", {}).get("data", [])
            c_data = chart.get("data", [])

            if any("1970-01" in str(x) for x in x_data):
                issues.append(
                    f"Biểu đồ '{c_title}' phát hiện lỗi Epoch Date '1970-01'. Cột năm (year) dạng số nguyên phải giữ nguyên kiểu int, không dùng pd.to_datetime()."
                )

            for row in c_data:
                if isinstance(row, dict):
                    for v in row.values():
                        if "1970-01" in str(v):
                            issues.append(
                                f"Biểu đồ '{c_title}' chứa giá trị Epoch Date '1970-01' trong data records."
                            )
                            break

            # 3. Check & Enforce Pie / Donut Anti-Overlap Config
            c_type = str(chart.get("type", "")).lower()
            if c_type in ["pie", "donut"]:
                chart["avoidLabelOverlap"] = True
                chart["minAngle"] = 5
                if "series" in chart and isinstance(chart["series"], list) and len(chart["series"]) > 0:
                    for s in chart["series"]:
                        s["avoidLabelOverlap"] = True
                        s["minAngle"] = 5
                        if "label" not in s or not isinstance(s["label"], dict):
                            s["label"] = {
                                "show": True,
                                "formatter": "{b}: {d}%",
                                "fontSize": 11,
                            }
                        else:
                            s["label"]["show"] = True
                            s["label"]["formatter"] = "{b}: {d}%"

            # 4. Check Cardinality Rules
            dim = (
                chart.get("dimension")
                or chart.get("category_col")
                or chart.get("name_key")
                or chart.get("x_axis_key")
                or chart.get("xAxisKey")
            )
            dim_str = str(dim) if dim else ""
            matched_col = None
            if dim_str:
                for c in df.columns:
                    if str(c).lower().replace(" ", "").replace("_", "") == dim_str.lower().replace(" ", "").replace("_", ""):
                        matched_col = c
                        break

            if c_type in ["pie", "donut"]:
                unique_count = int(df[matched_col].nunique()) if matched_col else len(c_data)
                non_other = [d for d in c_data if isinstance(d, dict) and d.get("name") != "Khác"]
                if unique_count > 7 or len(c_data) > 7 or len(non_other) > 6:
                    issues.append(
                        "Lỗi nghiêm trọng: Donut chart đang nhận cột có độ đa dạng quá lớn làm vỡ biểu đồ ('Khác: 99%'). "
                        "Hãy đổi Donut chart sang nhóm phân loại hẹp (<Low_Cardinality_Category> có nunique 2-7) và gán thực thể chính vào Bar Chart."
                    )
            elif c_type in ["bar", "ranking_bar"]:
                unique_count = int(df[matched_col].nunique()) if matched_col else 999
                has_entity = any(int(df[c].nunique()) >= 7 and not pd.api.types.is_numeric_dtype(df[c]) for c in df.columns)
                has_continuous_metric = any(pd.api.types.is_numeric_dtype(df[c]) for c in df.columns if c != matched_col)
                if unique_count <= 3 and has_entity and has_continuous_metric:
                    issues.append(
                        f"Biểu Đồ Phân Tích Chính (Bar Chart) đang dùng cột '{dim_str}' có Cardinality cực thấp ({unique_count} giá trị) với count(*). "
                        "Phải xếp hạng Top 10-15 Entity theo KPI đo lường chính."
                    )

        if issues:
            return False, " | ".join(issues)
        return True, ""

    async def _evaluate_storytelling_quality(
        self, df: pd.DataFrame, spec: dict[str, Any]
    ) -> tuple[bool, str]:
        """Sub-Agent B: Executive Storytelling Evaluator.

        Evaluates if Diễn Biến -> Nguyên Nhân -> Khuyến Nghị accurately reflects real dataset metrics.
        """
        summary_text = spec.get("summaryText") or spec.get("summary") or ""
        if not summary_text or len(summary_text.strip()) < 10:
            return False, "Nội dung nhận định (summaryText) quá ngắn hoặc rỗng."

        has_dien_bien = any(w in summary_text for w in ["Diễn biến", "Diễn Biến", "diễn biến"])
        has_nguyen_nhan = any(w in summary_text for w in ["Nguyên nhân", "Nguyên Nhân", "nguyên nhân"])
        has_khuyen_nghi = any(w in summary_text for w in ["Khuyến nghị", "Khuyến Nghị", "khuyến nghị"])

        if not (has_dien_bien and has_nguyen_nhan and has_khuyen_nghi):
            return False, "Nội dung nhận định thiếu định dạng 3 khối: Diễn Biến -> Nguyên Nhân -> Khuyến Nghị."

        return True, ""

    @staticmethod
    def _enrich_spec_with_full_dataset(spec: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
        """Post-processing step to lock in full dataset records (up to 5,000 rows) for AG-Grid."""
        if "table" not in spec or not isinstance(spec["table"], dict):
            spec["table"] = {}

        total_rows = len(df)
        total_cols = len(df.columns)

        spec["totalRows"] = total_rows
        spec["totalColumns"] = total_cols
        spec["total_rows"] = total_rows
        spec["total_cols"] = total_cols
        spec["total_records"] = total_rows
        spec["total_fields"] = total_cols

        import numpy as np
        cleaned_df = df.head(10000).replace({np.nan: None, np.inf: None, -np.inf: None})

        all_records = cleaned_df.to_dict(orient="records")
        spec["table"]["rows"] = all_records
        spec["raw_data"] = all_records
        spec["rawData"] = all_records
        spec["rawRows"] = all_records
        spec["rows"] = all_records

        if "columns" not in spec["table"] or not spec["table"]["columns"]:
            spec["table"]["columns"] = [
                {
                    "field": str(col),
                    "headerName": str(col).replace("_", " ").title(),
                    "sortable": True,
                    "filter": True,
                }
                for col in df.columns
            ]

        return spec

    async def _refine_dashboard_spec(
        self, df: pd.DataFrame, spec: dict[str, Any], combined_feedback: str
    ) -> dict[str, Any]:
        """Refine dashboard specification based on Sub-Agents critique feedback."""
        logger.info("Refining Dashboard Spec based on feedback: %s", combined_feedback)

        valid_cols = set(df.columns.tolist() + ["x", "y", "group_x", "name", "value"])

        # Fix Epoch Date and invalid column keys in chart data
        for chart in spec.get("charts", []):
            x_data = chart.get("x_data", [])
            if any("1970-01" in str(x) for x in x_data):
                cat_cols = [c for c in df.columns if not str(c).lower().endswith("_id")]
                if cat_cols:
                    col = cat_cols[0]
                    vc = df[col].astype(str).value_counts().head(15).reset_index()
                    chart["x_data"] = vc[col].tolist() if col in vc.columns else vc["index"].tolist()

            # Check if chart references a non-existent column key
            x_key = chart.get("x_axis_key") or chart.get("xAxisKey")
            y_key = chart.get("y_axis_key") or chart.get("yAxisKey")

            if (x_key and str(x_key).lower() not in valid_cols) or (y_key and str(y_key).lower() not in valid_cols) or not chart.get("data"):
                logger.warning(
                    "Auto-correcting chart '%s' due to invalid keys (x_key=%s, y_key=%s)",
                    chart.get("title"), x_key, y_key,
                )
                agg_data = self._execute_data_aggregation(
                    df,
                    {
                        "user_query": combined_feedback,
                        "x_axis": df.columns[0],
                        "group_by_type": "monthly" if any(w in str(combined_feedback).lower() for w in ["tháng", "month", "monthly"]) else "categorical",
                    },
                )
                chart["data"] = agg_data.get("bar_chart_data", [])
            # Sanitize chart data objects to strip extra auxiliary keys (like "month", "quarter")
            c_data = chart.get("data", [])
            if isinstance(c_data, list):
                clean_data = []
                has_date = False
                for row in c_data:
                    if isinstance(row, dict):
                        x_val = str(row.get("x", "") or row.get("name", "") or "")
                        if len(x_val) >= 7 and x_val[:4].isdigit() and x_val[4] in ["-", "/"] and x_val[5:7].isdigit():
                            has_date = True
                        clean_row = {
                            k: v for k, v in row.items()
                            if str(k).lower() in ["x", "y", "name", "value", "label", "series", "category"] or str(k).lower() in [c.lower() for c in df.columns]
                        }
                        clean_data.append(clean_row)
                chart["data"] = clean_data

                # Fix title consistency: if date data is present, title should reflect temporal trend
                c_title = str(chart.get("title", "")).lower()
                if has_date and any(term in c_title for term in ["danh mục", "category", "phân loại"]) and not any(t in c_title for t in ["thời gian", "tháng", "năm", "quý", "trend", "time", "date"]):
                    primary_col = str(chart.get("y_axis_key") or "Chỉ Số").replace("_", " ").title()
                    chart["title"] = f"Xu Hướng {primary_col} Theo Thời Gian"

            if chart.get("type") in ["pie", "donut"]:
                chart["avoidLabelOverlap"] = True
                chart["minAngle"] = 5

        spec = validate_and_correct_chart_specs(spec, {"cardinality": {str(c): int(df[c].nunique()) for c in df.columns}}, df)
        return self._enrich_spec_with_full_dataset(spec, df)

    def _assemble_dashboard_ast(
        self,
        exploration_data: dict[str, Any],
        layout_ast: dict[str, Any],
        charts_spec: list[dict[str, Any]],
        story_text: str,
        filename: str,
        df: pd.DataFrame,
    ) -> dict[str, Any]:
        """Assemble all sub-agent outputs into final Dashboard AST JSON Spec."""
        layout_type = exploration_data.get("layout_type", "full_dashboard")
        if layout_type == "single_chart" and charts_spec:
            charts_spec = [charts_spec[0]]

        total_rows = exploration_data["total_rows"]
        total_cols = exploration_data["total_cols"]

        return {
            "datasetName": filename,
            "layout_type": layout_type,
            "totalRows": total_rows,
            "totalColumns": total_cols,
            "total_rows": total_rows,
            "total_cols": total_cols,
            "total_records": total_rows,
            "total_fields": total_cols,
            "has_sales": exploration_data["has_sales"],
            "kpiCards": exploration_data["kpi_cards"],
            "kpis": exploration_data["kpi_cards"],
            "slicers": exploration_data.get("slicers", []),
            "valid_category_cols": exploration_data.get("valid_category_cols", []),
            "donut_pie_cat_cols": exploration_data.get("donut_pie_cat_cols", []),
            "charts": charts_spec,
            "layout": layout_ast,
            "summaryText": strip_emojis(story_text),
            "raw_data": exploration_data["table_rows"],
            "rawRows": exploration_data["table_rows"],
            "rows": exploration_data["table_rows"],
            "table": {
                "columns": exploration_data["table_cols"],
                "rows": exploration_data["table_rows"],
            },
        }

    def _autofix_dashboard_ast(
        self, dashboard_ast: dict[str, Any], exploration_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Deterministic Fallback Auto-Correction to fix layout & chart specs."""
        logger.info("Running deterministic Fallback Auto-Correction")
        layout_type = exploration_data.get("layout_type", "full_dashboard")
        dashboard_ast["layout_type"] = layout_type

        # Fix Layout Grid Spans to 12
        layout = {
            "grid_columns": 12,
            "rows": [
                {
                    "row_id": "row_kpis",
                    "col_span": 12,
                    "type": "kpi_grid",
                    "items": [
                        {"id": "kpi_1", "col_span": 3},
                        {"id": "kpi_2", "col_span": 3},
                        {"id": "kpi_3", "col_span": 3},
                        {"id": "kpi_4", "col_span": 3},
                    ],
                },
                {
                    "row_id": "row_charts",
                    "col_span": 12,
                    "type": "chart_grid",
                    "items": [
                        {"chart_id": "primary_chart_custom", "type": exploration_data.get("primary_chart_spec", {}).get("type", "bar"), "col_span": 12 if layout_type == "single_chart" else 7},
                        {"chart_id": "secondary_chart_proportion", "type": "pie", "col_span": 5},
                    ] if layout_type != "single_chart" else [
                        {"chart_id": "primary_chart_custom", "type": exploration_data.get("primary_chart_spec", {}).get("type", "bar"), "col_span": 12}
                    ],
                },
                {
                    "row_id": "row_table",
                    "col_span": 12,
                    "type": "data_table",
                    "items": [{"table_id": "main_table", "col_span": 12}],
                },
            ],
        }
        dashboard_ast["layout"] = layout

        # Fix Charts
        if exploration_data.get("primary_chart_spec"):
            p_spec = exploration_data["primary_chart_spec"]
            if layout_type == "single_chart":
                charts = [p_spec]
            else:
                s_spec = exploration_data.get("secondary_chart_spec") or {
                    "chart_id": "secondary_chart_proportion",
                    "type": "pie",
                    "title": "Tỷ Trọng Cơ Cấu",
                    "name_key": "name",
                    "value_key": "value",
                    "data": exploration_data.get("pie_chart_data", []),
                    "grid_span": 5,
                }
                charts = [p_spec, s_spec]
        else:
            bar_col_title = exploration_data["target_bar_col"].replace("_", " ").title()
            is_monetary = exploration_data["is_bar_monetary"]
            p_spec = {
                "chart_id": f"bar_{exploration_data['target_bar_col']}",
                "type": "bar",
                "title": f"Tổng {primary_metric_title or bar_col_title} Theo {bar_col_title}" if is_monetary else f"Phân Bổ Tần Suất Theo {bar_col_title}",
                "x_axis_key": "x",
                "y_axis_key": "y",
                "xAxisKey": "x",
                "yAxisKey": "y",
                "series_keys": ["y"],
                "dimension": exploration_data["target_bar_col"],
                "metric": exploration_data.get("primary_metric_name"),
                "measure": exploration_data.get("primary_metric_name"),
                "measure_col": exploration_data.get("primary_metric_name"),
                "isMonetary": is_monetary,
                "unit": str(exploration_data.get("primary_metric_name", "")).replace("_", " ").title() if is_monetary else "Đơn vị",
                "data": exploration_data["bar_chart_data"],
                "grid_span": 12 if layout_type == "single_chart" else 7,
            }
            if layout_type == "single_chart":
                charts = [p_spec]
            else:
                charts = [
                    p_spec,
                    {
                        "chart_id": "chart_pie_composition",
                        "type": "donut",
                        "title": f"Tỷ Trọng Theo {exploration_data['target_pie_col'].replace('_', ' ').title()}",
                        "subtitle": f"Phân bổ dựa trên cột '{exploration_data.get('primary_metric_name') or 'count'}' theo từng '{exploration_data['target_pie_col']}'" if exploration_data.get('primary_metric_name') else f"Số lượng giao dịch (Đếm số dòng theo '{exploration_data['target_pie_col']}')",
                        "name_key": "name",
                        "value_key": "value",
                        "dimension": exploration_data["target_pie_col"],
                        "measure": exploration_data.get("primary_metric_name") or "count",
                        "aggregation": "SUM" if exploration_data.get("primary_metric_name") else "COUNT",
                        "data": exploration_data["pie_chart_data"],
                        "grid_span": 5,
                    },
                ]
        dashboard_ast["charts"] = charts

        # Ensure KPIs exist
        if not dashboard_ast.get("kpiCards"):
            dashboard_ast["kpiCards"] = exploration_data["kpi_cards"]
            dashboard_ast["kpis"] = exploration_data["kpi_cards"]

        # Apply validate_and_correct_chart_specs
        df_target = exploration_data.get("df")
        dashboard_ast = validate_and_correct_chart_specs(dashboard_ast, exploration_data, df_target)
        if df_target is not None:
            dashboard_ast = self._enrich_spec_with_full_dataset(dashboard_ast, df_target)

        return dashboard_ast

    @staticmethod
    def _validate_code_safety(code: str) -> Optional[str]:
        """Check generated code for forbidden operations."""
        match: Optional[re.Match[str]] = _FORBIDDEN_RE.search(code)
        if match:
            return f"Phát hiện lệnh nguy hiểm: '{match.group()}'"
        return None
