"""The analysis sandbox as a separate service: signed requests, same results as a local run, fail closed."""
import json
import threading

import httpx
import pandas as pd
import pytest

from src.agents.data_agent import sandbox_server
from src.agents.data_agent.sandbox import SafePythonSandbox, sign_request

SECRET = "a-shared-secret-of-enough-length"
FRAME = pd.DataFrame({
    "region": ["north", "south", "north", "east"],
    "sales": [10.0, 20.0, 30.0, 5.0],
    "day": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
})
CODE = "result = df.groupby('region')['sales'].sum().sort_values(ascending=False)"


@pytest.fixture
def server():
    httpd = sandbox_server.serve(SECRET, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def remote(url, secret=SECRET, **kw):
    return SafePythonSandbox(timeout_seconds=kw.pop("timeout_seconds", 10.0), remote_url=url, remote_secret=secret, **kw)


def test_a_remote_run_gives_the_same_answer_as_a_local_one(server):
    here = SafePythonSandbox().execute_sync(CODE, FRAME)
    there = remote(server).execute_sync(CODE, FRAME)
    assert there.success and here.success
    assert there.table == here.table
    assert there.table["columns"] == ["region", "value"] and there.table["rows"][0] == ["north", 40.0]


def test_dates_and_text_survive_the_trip_as_parquet(server):
    result = remote(server).execute_sync("result = {'first': str(df['day'].min().date()), 'dtype': str(df['day'].dtype)[:10], 'n': int(len(df))}", FRAME)
    assert result.success and result.result_data == {"first": "2026-01-01", "dtype": "datetime64", "n": 4}


def test_unsafe_code_is_refused_here_and_never_sent(server):
    refused = remote("http://127.0.0.1:9").execute_sync("import os\nresult = os.listdir('/')", FRAME)  # nothing listens on port 9
    assert not refused.success and "Chính sách bảo mật" in refused.error  # the allow-list answered, not a network error


def test_when_the_sandbox_cannot_be_reached_the_code_is_not_run_anywhere_else():
    result = remote("http://127.0.0.1:9").execute_sync("result = 1 + 1", FRAME)
    assert not result.success and "không khả dụng" in result.error  # no silent fallback next to the API's secrets


def test_a_wrong_secret_is_rejected_by_the_service(server):
    result = remote(server, secret="not-the-shared-secret-at-all").execute_sync("result = 1", FRAME)
    assert not result.success and "từ chối" in result.error


def test_requests_without_a_valid_signature_get_401_and_garbage_does_not_kill_the_server(server):
    body = json.dumps({"code": "result = 1"}).encode()
    assert httpx.post(f"{server}/run", content=body).status_code == 401
    assert httpx.post(f"{server}/run", content=body, headers={"X-Signature": "0" * 64}).status_code == 401
    junk = b"not json"
    assert httpx.post(f"{server}/run", content=junk, headers={"X-Signature": sign_request(SECRET, junk)}).status_code == 400
    assert httpx.get(f"{server}/health").json() == {"status": "ok"}  # still serving
    assert httpx.get(f"{server}/nope").status_code == 404


def test_the_service_clamps_the_limits_a_caller_asks_for(server, monkeypatch):
    monkeypatch.setattr(sandbox_server, "MAX_TIMEOUT_SECONDS", 2.0)
    started = pd.Timestamp.now()
    result = remote(server, timeout_seconds=600.0).execute_sync("while True:\n    pass", FRAME)
    assert not result.success and (pd.Timestamp.now() - started).total_seconds() < 30  # cut at ~2 s (+ grace), not 600


def test_a_frame_parquet_cannot_hold_is_reported_not_crashed(server):
    mixed = pd.DataFrame({"x": [1, "a", object()]})
    result = remote(server).execute_sync("result = 1", mixed)
    assert not result.success and "sandbox" in result.error.lower()


def test_the_service_refuses_to_start_with_a_weak_secret():
    with pytest.raises(SystemExit):
        sandbox_server.serve("short")
