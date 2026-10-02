"""Data agent end to end (real pipeline, fake LLM): upload -> routing -> verified spec / summary / computed answer."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from src.agents.data_agent.agent import DataAnalystAgent
from src.orchestrator.core import Orchestrator
from src.orchestrator.verifier import verify_dashboard_spec
from src.agents.data_agent.ingest import safe_read_csv
from tests.test_insights import _planted


class FakeLLM:
    """Writes pandas code for QA prompts; everything else (story polish, narration) gets unusable text."""

    def __init__(self, code: str = "result = df.groupby('region')['revenue'].sum().sort_values(ascending=False).head(3).reset_index()"):
        self.code = code
        self.prompts: list[str] = []

    async def chat_completion(self, messages, **kwargs):
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        text = f"```python\n{self.code}\n```" if "You write pandas code" in prompt else "not json"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture(scope="module")
def csv_text() -> str:
    return _planted().to_csv(index=False)


def run(agent: DataAnalystAgent, query: str, content, filename: str = "sales.csv") -> dict:
    return json.loads(asyncio.run(agent.process_csv_request(query, content, filename, "s1")))


@pytest.fixture()
def agent() -> DataAnalystAgent:
    return DataAnalystAgent(FakeLLM(), model="fake")


def test_dashboard_is_verified_and_self_consistent(agent, csv_text):
    reply = run(agent, "Dựng dashboard cho dữ liệu này", csv_text)
    spec = reply["dashboard_spec"]
    assert reply["type"] == "dashboard" and reply["pev_trace"]["is_verified"] is True
    assert spec["version"] == 2 and spec["language"] == "vi" and len(spec["charts"]) >= 3 and spec["kpis"]
    assert spec["table"]["totalRows"] == 4380 and len(spec["table"]["rows"]) == 4380 and not spec["table"]["truncated"]
    assert all(c["insight"] or not c["fact_ids"] for c in spec["charts"])
    slicers = {s["field"]: s["values"] for s in spec["slicers"]}
    assert set(slicers["region"]) == {"North", "South", "East", "West"} and slicers["region"][0] == "North"  # most frequent first
    # an independent audit against the file itself agrees
    assert verify_dashboard_spec(safe_read_csv(csv_text), spec) == (True, "VERIFIED: every chart, KPI and story number matches the dataset.")
    # the spec is strict JSON (no NaN) and carries no duplicated row copies
    json.dumps(reply, allow_nan=False)
    assert not {"raw_data", "rawData", "rawRows", "rows"} & set(spec)


def test_output_language_follows_the_question(agent, csv_text):
    english = run(agent, "Build a dashboard of this data", csv_text)["dashboard_spec"]
    assert english["language"] == "en" and english["kpis"][0]["title"] == "Records"


def test_a_tampered_spec_is_caught_by_the_audit(agent, csv_text):
    spec = copy.deepcopy(run(agent, "dashboard", csv_text)["dashboard_spec"])
    spec["charts"][0]["data"][0]["y"] = (spec["charts"][0]["data"][0].get("y") or 1) * 2
    ok, feedback = verify_dashboard_spec(safe_read_csv(csv_text), spec)
    assert not ok and "does not match the data" in feedback


def test_orchestrator_audit_accepts_real_output_and_rejects_forged_kpis(agent, csv_text):
    parsed = run(agent, "dashboard", csv_text)
    assert Orchestrator._audit_dashboard(csv_text, copy.deepcopy(parsed), 0) == {"is_verified": True, "verifier_feedback": ""}
    parsed["dashboard_spec"]["kpis"][0]["raw_value"] += 1
    verdict = Orchestrator._audit_dashboard(csv_text, parsed, 0)
    assert verdict["is_verified"] is False and "KPI" in verdict["verifier_feedback"]


def test_summary_request_returns_text_with_column_table(agent, csv_text):
    reply = run(agent, "Tóm tắt dữ liệu", csv_text)
    assert reply["type"] == "text_summary" and "dashboard_spec" not in reply
    assert "| Cột |" in reply["content"] and reply["metadata"]["total_rows"] == 4380


def test_question_is_answered_with_computed_numbers(csv_text):
    llm = FakeLLM()
    reply = run(DataAnalystAgent(llm, model="fake"), "Top 3 khu vực theo doanh thu?", csv_text)
    expected = _planted().groupby("region")["revenue"].sum().sort_values(ascending=False)
    assert reply["type"] == "text_summary" and reply["table"]["rows"][0][0] == expected.index[0]
    assert reply["generated_code"].startswith("result =")


def test_unsafe_generated_code_falls_back_to_the_summary(csv_text):
    bad = DataAnalystAgent(FakeLLM(code="import os\nresult = os.listdir('.')"), model="fake")
    reply = run(bad, "How many rows have revenue above 100?", csv_text)
    assert "could not compute" in reply["content"] and "Summary of" in reply["content"]


def test_orchestrator_notes_do_not_change_language_or_intent(agent, csv_text):
    query = "Summarise this file\n\n[Yêu cầu định dạng: Trả lời bằng Markdown phân tích ngắn gọn kèm bảng thống kê nếu cần, TUYỆT ĐỐI KHÔNG sinh cấu trúc dashboard_spec.]"
    reply = run(agent, query, csv_text)
    assert reply["type"] == "text_summary" and "Summary of" in reply["content"]


@pytest.mark.parametrize("content", [b"", b"\x00\x01\x02binary"])
def test_unreadable_files_get_a_friendly_error_not_a_crash(agent, content):
    reply = run(agent, "dashboard", content, "bad.csv")
    assert reply["status"] == "error" and reply["type"] == "error" and reply["content"]


def test_oversize_upload_is_refused_before_parsing(agent, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "DATA_MAX_FILE_MB", 0)
    reply = run(agent, "dashboard", "a,b\n1,2\n")
    assert reply["type"] == "error" and "sales.csv" in reply["content"]


def test_without_a_file_the_agent_explains_what_to_upload(agent):
    reply = json.loads(asyncio.run(agent.process_request("phân tích giúp tôi", "s1")))
    assert reply["type"] == "text" and "CSV" in reply["content"]


def test_filtering_recomputes_verified_charts_and_kpis_for_the_selected_rows(agent, csv_text):
    spec = run(agent, "dashboard", csv_text)["dashboard_spec"]
    specs = [c["spec"] for c in spec["charts"] if c["type"] != "waterfall"]
    filtered = asyncio.run(agent.filter_dashboard("s1", specs, {"region": ["North", "East"]}, "en"))

    frame = _planted()
    subset = frame[frame["region"].isin(["North", "East"])]
    assert filtered["rows_used"] == len(subset) and filtered["rows_total"] == len(frame) and filtered["verified"] is True
    total = next(k for k in filtered["kpis"] if k["id"].endswith("_sum"))
    assert total["raw_value"] == pytest.approx(subset["revenue"].sum(), rel=1e-4)
    assert next(k for k in filtered["kpis"] if k["id"] == "kpi_records")["raw_value"] == len(subset)
    donut = next(c for c in filtered["charts"] if c and c["type"] == "donut")
    assert sum(d["value"] for d in donut["data"]) == pytest.approx(subset["units"].sum() if donut["measure"] == "units" else subset["revenue"].sum() if donut["measure"] == "revenue" else len(subset), rel=1e-4)
    json.dumps(filtered, allow_nan=False)


def test_filtering_rejects_bad_columns_missing_sessions_and_empty_results(agent, csv_text):
    spec = run(agent, "dashboard", csv_text)["dashboard_spec"]
    specs = [c["spec"] for c in spec["charts"]][:1]
    with pytest.raises(ValueError, match="not a filterable"):
        asyncio.run(agent.filter_dashboard("s1", specs, {"revenue": ["1"]}))
    with pytest.raises(ValueError):
        asyncio.run(agent.filter_dashboard("s1", [{"id": "x", "type": "nonsense"}], {}))
    with pytest.raises(LookupError):
        asyncio.run(agent.filter_dashboard("unknown-session", specs, {}))
    nothing = asyncio.run(agent.filter_dashboard("s1", specs, {"region": ["Atlantis"]}))
    assert nothing["rows_used"] == 0 and nothing["charts"] == [] and nothing["kpis"] == []


def test_excel_upload_end_to_end(agent, csv_text):
    import io

    import pandas as pd

    buffer = io.BytesIO()
    pd.read_csv(io.StringIO(csv_text)).head(400).to_excel(buffer, index=False)
    reply = run(agent, "dashboard", buffer.getvalue(), "sales.xlsx")
    assert reply["type"] == "dashboard" and reply["pev_trace"]["is_verified"] and reply["dashboard_spec"]["analysis"]["format"] == "excel"
