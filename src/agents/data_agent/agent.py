"""Data analyst agent: turns an uploaded table into a verified dashboard, a text summary or a computed answer.

Pipeline (each step lives in its own module, this file only wires them together):

    ingest -> profile -> insights -> plan + compile charts -> KPIs -> story -> verify -> spec v2

Intent routing for one request:  dashboard request -> dashboard | summary request -> text summary |
anything else -> a question answered by code the LLM writes and the sandbox runs (falls back to the summary).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from src.agents.base_agent import BaseAgent
from src.agents.data_agent import compute
from src.agents.data_agent.charts import ChartContext, ChartSpec, build_kpis, compile_chart, plan_dashboard, plan_single_chart
from src.agents.data_agent.i18n import detect_language, format_number, format_pct, tr
from src.agents.data_agent.ingest import Dataset, load_dataset, safe_read_csv  # noqa: F401  (safe_read_csv: re-exported for the verifier)
from src.agents.data_agent.insights import Insight, generate_insights
from src.agents.data_agent.intent import parse_query_hints
from src.agents.data_agent.profiler import (
    ROLE_BOOLEAN,
    ROLE_HIGH_CARDINALITY,
    ROLE_IDENTIFIER,
    ROLE_LOW_CARDINALITY,
    ROLE_MEASURE,
    ROLE_ORDINAL,
    ROLE_RATIO,
    ROLE_TEMPORAL,
    profile_dataframe_universal,
)
from src.agents.data_agent.qa import answer_question
from src.agents.data_agent.sandbox import SafePythonSandbox, SandboxResult
from src.agents.data_agent.story import annotate_charts, build_story, polish_story, story_to_markdown
from src.config import settings
from src.orchestrator.verifier import auto_remediate_chart_specs, verify_dashboard_spec
from src.shared.dataset_reader import DatasetReadError
from src.shared.intents import is_dashboard_request, is_summary_request, is_text_only_request, wants_single_chart
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

SPEC_VERSION = 2
_NOTE_SUFFIX = re.compile(r"\n\n\[(?:Ghi chú từ Verifier|Yêu cầu định dạng)[^\]]*\]\s*", re.DOTALL)
_MAX_SUMMARY_COLUMNS = 40
_SESSION_CACHE = 8
_MAX_SLICERS = 4
_MAX_SLICER_VALUES = 30


@dataclass
class _Analysis:
    """Everything derived from the upload that both the dashboard and the summary need."""

    dataset: Dataset
    profile: dict[str, Any]
    facts: list[Insight]


def _json_safe(value: Any) -> Any:
    """Recursively make a value strict-JSON serialisable (NaN/inf -> null, numpy -> python)."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)
    return value


def _table_rows(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    """First ``limit`` rows as JSON-safe records (dates as ISO text, missing values as null)."""
    part = df.head(limit).copy()
    for column in part.columns:
        if pd.api.types.is_datetime64_any_dtype(part[column]):
            text = part[column].dt.strftime("%Y-%m-%d %H:%M:%S")
            part[column] = text.str.replace(" 00:00:00", "", regex=False)
    part = part.replace([np.inf, -np.inf], np.nan).astype(object)
    return part.where(part.notna(), None).to_dict(orient="records")


def _column_type(profile: dict[str, Any], column: str) -> str:
    role = profile["role_map"][column]
    if role == ROLE_TEMPORAL:
        return "date"
    return "number" if role in (ROLE_MEASURE, ROLE_RATIO, ROLE_ORDINAL) else "text"


def _column_details(info: dict[str, Any], lang: str) -> str:
    role = info["role"]
    if role in (ROLE_MEASURE, ROLE_RATIO, ROLE_ORDINAL) and "min" in info:
        low, high, mean = (format_number(info[k]) for k in ("min", "max", "mean"))
        return tr(lang, "detail.range", low=low, high=high, mean=mean)
    if role == ROLE_TEMPORAL:
        return tr(lang, "detail.dates", low=info.get("min_date"), high=info.get("max_date"))
    if role in (ROLE_LOW_CARDINALITY, ROLE_HIGH_CARDINALITY, ROLE_BOOLEAN) and info.get("top_values"):
        top = info["top_values"][0]
        return tr(lang, "detail.top", value=str(top["value"])[:40], share=format_pct(top["share"]))
    if role == ROLE_IDENTIFIER:
        return tr(lang, "detail.distinct", n=format_number(float(info["nunique"])))
    return ""


def _escape_cell(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|")


class DataAnalystAgent(BaseAgent):
    """Verified data analysis: dashboards, summaries and computed answers over an uploaded table."""

    def __init__(
        self,
        llm_client: LLMClient,
        model: str = "openai/gpt-4o-mini",
        mcp_client: Optional[Any] = None,
        redis_client: Optional[Any] = None,
    ) -> None:
        self.llm_client: LLMClient = llm_client
        self.model: str = model
        self.mcp_client: Optional[Any] = mcp_client
        self.redis_client: Optional[Any] = redis_client
        self.sandbox: SafePythonSandbox = SafePythonSandbox(
            timeout_seconds=10.0, remote_url=settings.SANDBOX_URL, remote_secret=settings.SANDBOX_SECRET
        )
        # ponytail: per-process LRU of analysed sessions (filtering re-uses it); a restart re-analyses from Redis
        self._sessions: OrderedDict[str, _Analysis] = OrderedDict()

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def get_metadata(self) -> dict[str, str]:
        return {
            "name": "data_agent",
            "description": (
                "Chuyên phân tích dữ liệu bảng (CSV, Excel, Parquet, JSON): tóm tắt dữ liệu, tính KPI, "
                "dựng dashboard biểu đồ tương tác đã kiểm chứng số liệu, kể câu chuyện dữ liệu (insight) "
                "và trả lời câu hỏi thống kê bằng số liệu tính toán thật."
            ),
        }

    async def execute_sandbox_code(self, code: str, df: Optional[pd.DataFrame] = None) -> SandboxResult:
        """Run custom analysis code in the isolated sandbox."""
        return await self.sandbox.execute_async(code=code, df=df)

    @staticmethod
    def _is_dashboard_request(query: str) -> bool:
        return is_dashboard_request(query)

    async def process_request(self, query: str, session_id: str) -> str:
        """Text-only request: reuse the session's uploaded file if there is one, else explain what to do."""
        lang = detect_language(self._clean_query(query))
        if self.redis_client is not None:
            try:
                active = await self.redis_client.get_active_file(session_id=session_id)
                if active and active.get("csv_content"):
                    return await self.process_csv_request(
                        query=query, csv_content=active["csv_content"], filename=active.get("filename", "dataset.csv"), session_id=session_id
                    )
            except Exception as exc:  # noqa: BLE001 - Redis is a convenience cache
                logger.warning("Active file recovery skipped: %s", exc, extra={"session_id": session_id})
        return self._reply(text=tr(lang, "err.no_file"), type_="text")

    async def process_csv_request(self, query: str, csv_content: Union[str, bytes], filename: str, session_id: str) -> str:
        """Analyse an uploaded table according to what ``query`` asks for; always returns a JSON string."""
        full_query = query or ""
        query = self._clean_query(full_query)
        lang = detect_language(query, default=detect_language(filename))
        size = len(csv_content) if isinstance(csv_content, bytes) else len(csv_content.encode("utf-8", errors="replace"))
        if size > settings.DATA_MAX_FILE_MB * 1024 * 1024:
            return self._reply(text=tr(lang, "err.too_large", name=filename, mb=settings.DATA_MAX_FILE_MB), type_="error")

        await self._remember_file(session_id, filename, csv_content)
        try:
            analysis = await asyncio.to_thread(self._analyse, csv_content, filename)
        except DatasetReadError as exc:
            logger.info("Unreadable upload '%s': %s", filename, exc, extra={"session_id": session_id})
            return self._reply(text=tr(lang, f"err.{exc.code}"), type_="error")
        self._keep(session_id, analysis)

        text_only = is_text_only_request(full_query)
        if is_dashboard_request(query) and not text_only:
            return await self._dashboard_reply(analysis, query, filename, lang, session_id)
        if not is_summary_request(query) and query.strip():
            answered = await answer_question(
                query, analysis.dataset.df, analysis.profile, lang, self.llm_client, self.sandbox, self.model, session_id
            )
            if answered:
                return self._reply(text=answered.answer, type_="text_summary", metadata=self._metadata(analysis, filename),
                                   extra={"table": answered.table, "generated_code": answered.code})
            logger.info("No computed answer for '%s'; falling back to the summary", query[:80], extra={"session_id": session_id})
            return await self._summary_reply(analysis, filename, lang, prefix=tr(lang, "qa.no_result"))
        return await self._summary_reply(analysis, filename, lang)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_query(query: str) -> str:
        """The user's own words: without notes the orchestrator appended (verifier feedback, format hints)."""
        return _NOTE_SUFFIX.sub("", query or "").strip()

    async def _remember_file(self, session_id: str, filename: str, content: Union[str, bytes]) -> None:
        if self.redis_client is None or not content:
            return
        try:
            text = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
            await self.redis_client.set_active_file(session_id=session_id, filename=filename, csv_content=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not cache the active file: %s", exc, extra={"session_id": session_id})

    @staticmethod
    def _analyse(content: Union[str, bytes], filename: str, with_facts: bool = True) -> _Analysis:
        """Load, profile and mine the table (CPU bound: run in a worker thread)."""
        # Text content is already-normalised CSV: the file name (e.g. ``.xlsx``) no longer describes it.
        dataset = load_dataset(content, filename if isinstance(content, bytes) else "")
        profile = profile_dataframe_universal(dataset.df, dataset.labels, dataset.hints())
        return _Analysis(dataset, profile, generate_insights(dataset.df, profile) if with_facts else [])

    def _keep(self, session_id: str, analysis: _Analysis) -> None:
        self._sessions[session_id] = analysis
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > _SESSION_CACHE:
            self._sessions.popitem(last=False)

    @staticmethod
    def _metadata(analysis: _Analysis, filename: str) -> dict[str, Any]:
        df = analysis.dataset.df
        return {"total_rows": analysis.dataset.meta["rows_total"], "total_cols": len(df.columns), "columns": list(df.columns), "file_name": filename}

    @staticmethod
    def _reply(text: str, type_: str, metadata: Optional[dict[str, Any]] = None, extra: Optional[dict[str, Any]] = None) -> str:
        payload = {
            "status": "error" if type_ == "error" else "success",
            "type": type_,
            "content": text,
            "explanation": text,
            "generated_code": "",
            **(extra or {}),
        }
        if metadata:
            payload["metadata"] = metadata
        return json.dumps(_json_safe(payload), ensure_ascii=False)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _summary_markdown(self, analysis: _Analysis, filename: str, lang: str, story: dict[str, Any]) -> str:
        profile, dataset = analysis.profile, analysis.dataset
        lines = [
            f"### {tr(lang, 'summary.title', name=filename)}",
            tr(lang, "summary.shape", rows=format_number(float(dataset.meta["rows_used"])), cols=profile["total_cols"]),
            "",
            story_to_markdown(story),
            "",
            f"### {tr(lang, 'summary.columns')}",
            f"| {tr(lang, 'summary.col.name')} | {tr(lang, 'summary.col.type')} | {tr(lang, 'summary.col.missing')} | {tr(lang, 'summary.col.details')} |",
            "| --- | --- | --- | --- |",
        ]
        for name, info in list(profile["columns"].items())[:_MAX_SUMMARY_COLUMNS]:
            lines.append(
                f"| {_escape_cell(info['label'])} | {tr(lang, 'role.' + info['role'])} | {format_pct(info['missing_pct'])} | {_escape_cell(_column_details(info, lang))} |"
            )
        if len(profile["columns"]) > _MAX_SUMMARY_COLUMNS:
            lines.append(tr(lang, "qa.rows_shown", shown=_MAX_SUMMARY_COLUMNS, total=format_number(float(len(profile["columns"])))))
        return "\n".join(lines)

    async def _summary_reply(self, analysis: _Analysis, filename: str, lang: str, prefix: str = "") -> str:
        story = build_story(analysis.facts, analysis.profile, analysis.dataset.meta, lang)
        text = await asyncio.to_thread(self._summary_markdown, analysis, filename, lang, story)
        return self._reply(text=f"{prefix}\n\n{text}" if prefix else text, type_="text_summary", metadata=self._metadata(analysis, filename))

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @staticmethod
    def _slicers(df: pd.DataFrame, profile: dict[str, Any]) -> list[dict[str, Any]]:
        """Filterable columns with every value (computed on the whole dataset, most frequent first)."""
        picked = [c for c in profile["dimensions"] if profile["role_map"][c] != ROLE_IDENTIFIER and 2 <= profile["columns"][c]["nunique"] <= _MAX_SLICER_VALUES]
        return [
            {"field": c, "label": profile["labels"][c], "values": df[c].astype("string").value_counts().index.tolist()}
            for c in picked[:_MAX_SLICERS]
        ]

    def _assemble(self, analysis: _Analysis, query: str, filename: str, lang: str, story: dict[str, Any], charts: list[dict[str, Any]], kpis: list[dict[str, Any]]) -> dict[str, Any]:
        dataset, profile = analysis.dataset, analysis.profile
        df, meta = dataset.df, dataset.meta
        return {
            "version": SPEC_VERSION,
            "language": lang,
            "mode": "single_chart" if wants_single_chart(query) and len(charts) == 1 else "dashboard",
            "title": f"{tr(lang, 'dashboard')} — {filename}",
            "fileName": filename,
            "summaryText": story_to_markdown(story),
            "story": story,
            "facts": [f.to_dict() for f in analysis.facts],
            "kpis": kpis,
            "charts": charts,
            "slicers": self._slicers(df, profile),
            "table": {
                "title": f"{tr(lang, 'table')} ({filename})",
                "columns": [
                    {"field": c, "headerName": profile["labels"][c], "type": _column_type(profile, c), "role": profile["role_map"][c],
                     "agg": profile["columns"][c].get("agg"), "unit": profile["columns"][c].get("unit_kind")}
                    for c in df.columns
                ],
                "rows": _table_rows(df, settings.DATA_TABLE_ROWS),
                "totalRows": len(df),
                "truncated": len(df) > settings.DATA_TABLE_ROWS,
            },
            "time": {k: v for k, v in profile["time"].items() if k in ("primary", "grain", "min", "max", "span_days")},
            "analysis": {
                "rows_total": meta["rows_total"],
                "rows_used": meta["rows_used"],
                "sampled": meta["sampled"],
                "format": meta["format"],
                "notes": meta["notes"],
                "warnings": profile["quality"]["warnings"],
                "hints": dataset.hints(),
            },
        }

    def _build_dashboard(self, analysis: _Analysis, query: str, filename: str, lang: str) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        """Plan and compile the charts and KPIs and assemble spec v2 without the story's LLM polish (thread work)."""
        profile, df = analysis.profile, analysis.dataset.df
        hints = parse_query_hints(query, profile)
        specs = plan_single_chart(profile, hints) if wants_single_chart(query) else []
        specs = specs or plan_dashboard(profile, analysis.facts, hints)
        ctx = ChartContext(df=df, profile=profile, lang=lang, facts={f.id: f for f in analysis.facts})
        charts = [chart for chart in (compile_chart(spec, ctx) for spec in specs) if chart]
        if not charts:
            return None, None
        story = build_story(analysis.facts, profile, analysis.dataset.meta, lang)
        annotate_charts(charts, story, analysis.facts, profile["labels"])
        focus = hints.pick(profile, (ROLE_MEASURE, ROLE_RATIO, ROLE_ORDINAL))
        return self._assemble(analysis, query, filename, lang, story, charts, build_kpis(ctx, analysis.facts, focus=focus)), story

    def _verify(self, analysis: _Analysis, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Verify against the data; on rejection repair deterministically once. Returns ``(spec, pev_trace)``."""
        df, profile = analysis.dataset.df, analysis.profile
        ok, feedback = verify_dashboard_spec(df, spec, profile)
        trace: dict[str, Any] = {"retry_count": 0, "is_verified": ok, "error_feedback": [] if ok else [feedback]}
        if not ok:
            logger.warning("Dashboard rejected by the verifier, repairing: %s", feedback)
            spec = auto_remediate_chart_specs(df, spec)
            ok, feedback = verify_dashboard_spec(df, spec, profile)
            trace.update(retry_count=1, is_verified=ok)
            if not ok:
                trace["error_feedback"].append(feedback)
        return spec, trace

    # ------------------------------------------------------------------
    # Interactive filtering (charts are recomputed by the same compiler, then re-verified)
    # ------------------------------------------------------------------

    async def _analysis_for(self, session_id: str) -> Optional[_Analysis]:
        if session_id in self._sessions:
            self._sessions.move_to_end(session_id)
            return self._sessions[session_id]
        if self.redis_client is None:
            return None
        active = await self.redis_client.get_active_file(session_id=session_id)
        if not active or not active.get("csv_content"):
            return None
        analysis = await asyncio.to_thread(self._analyse, active["csv_content"], active.get("filename", ""), False)
        self._keep(session_id, analysis)
        return analysis

    def _filtered(self, analysis: _Analysis, chart_specs: list[dict[str, Any]], filters: dict[str, list[str]], lang: str, focus: Optional[str]) -> dict[str, Any]:
        df, profile = analysis.dataset.df, analysis.profile
        mask = pd.Series(True, index=df.index)
        for column, values in filters.items():
            if column not in profile["dimensions"]:
                raise ValueError(f"'{column}' is not a filterable column")
            mask &= df[column].astype("string").isin([str(v) for v in values])
        subset = df[mask]

        result: dict[str, Any] = {"rows_used": len(subset), "rows_total": len(df), "charts": [], "kpis": [], "verified": True}
        if subset.empty:
            return result

        ctx = ChartContext(df=subset, profile=profile, lang=lang)  # no facts: findings describe the full dataset
        charts = [compile_chart(ChartSpec(**spec), ctx) for spec in chart_specs]
        kpis = build_kpis(ctx, [], focus=focus)
        time_col = profile["time"].get("primary")
        for card in [c for c in kpis if c["id"] == "kpi_time"]:  # the range card must describe the subset, not the file
            dates = compute.as_datetime(subset, time_col).dropna() if time_col else pd.Series(dtype="datetime64[ns]")
            if dates.empty:
                kpis.remove(card)
            else:
                card["value"] = card["subtitle"] = f"{dates.min().date()} → {dates.max().date()}"
                card["raw_value"] = float((dates.max() - dates.min()).days)
        result.update(charts=charts, kpis=kpis)

        compiled = [c for c in charts if c]
        if compiled:
            probe = {"language": lang, "kpis": kpis, "charts": compiled, "analysis": {"hints": analysis.dataset.hints()}}
            result["verified"] = verify_dashboard_spec(subset, probe, profile)[0]
        return result

    async def filter_dashboard(
        self, session_id: str, chart_specs: list[dict[str, Any]], filters: dict[str, list[str]], lang: str = "en", focus: Optional[str] = None
    ) -> dict[str, Any]:
        """Recompute a dashboard's charts and KPIs for the rows matching ``filters`` ({column: [values]}).

        ``focus`` is the dashboard's lead measure so the KPI cards keep the same layout.

        Raises:
            LookupError: no dataset is active for the session.
            ValueError: a filter column is not a dimension, or a chart spec is invalid.
        """
        analysis = await self._analysis_for(session_id)
        if analysis is None:
            raise LookupError("no active dataset for this session")
        return _json_safe(await asyncio.to_thread(self._filtered, analysis, chart_specs, filters, lang, focus))

    async def _dashboard_reply(self, analysis: _Analysis, query: str, filename: str, lang: str, session_id: str) -> str:
        spec, story = await asyncio.to_thread(self._build_dashboard, analysis, query, filename, lang)
        if spec is None or story is None:
            return await self._summary_reply(analysis, filename, lang, prefix=tr(lang, "err.no_chart"))

        polished = await polish_story(story, analysis.facts, analysis.profile, analysis.dataset.meta, self.llm_client, self.model, session_id)
        if polished["source"] == "llm":
            spec["story"], spec["summaryText"] = polished, story_to_markdown(polished)
            annotate_charts(spec["charts"], polished, analysis.facts, analysis.profile["labels"])

        spec, trace = await asyncio.to_thread(self._verify, analysis, spec)
        spec["verified"] = trace["is_verified"]
        payload = {
            "status": "success",
            "type": "dashboard",
            "explanation": spec["story"]["headline"],  # the full story is in the dashboard; the chat bubble stays short
            "dashboard_spec": _json_safe(spec),
            "generated_code": "",
            "pev_trace": trace,
        }
        return json.dumps(payload, ensure_ascii=False)
