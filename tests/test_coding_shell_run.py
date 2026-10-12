"""The shell itself: it is off unless the sandbox is told to allow it, every command is recorded, a command that changes protected files is undone,
a command that runs too long is killed, and a command that changes files makes earlier test results stale. (Linux-only behaviour such as the
resource limits and the signing key leaving /proc is checked inside the real container, see docs/CODING_AGENT.md.)"""
import asyncio
import shutil
import sys

import pytest

from src.agents.coding_agent import controller
from src.agents.coding_agent.workspace import Workspace, WorkspaceError

from tests.test_coding_agent import LocalExecutor, ScriptedLLM, tool_call, turn
from tests.test_coding_workspace import REPO, make_tar

pytestmark = pytest.mark.skipif(shutil.which("bash") is None and shutil.which("sh") is None, reason="needs a POSIX shell on PATH")
PY = "python"


@pytest.fixture()
def shell_on(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_ALLOW_SHELL", "1")


@pytest.fixture()
def ws(tmp_path):
    workspace = Workspace(tmp_path / "w")
    workspace.root.mkdir()
    workspace.load_tar(make_tar(REPO))
    return workspace


def test_the_shell_does_not_exist_unless_the_sandbox_switches_it_on(ws, monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX_ALLOW_SHELL", raising=False)
    assert "switched off" in ws.call("run_shell", {"command": "echo hi"})["error"]
    monkeypatch.setenv("CODE_SANDBOX_ALLOW_SHELL", "0")
    assert "switched off" in ws.call("run_shell", {"command": "echo hi"})["error"]
    with pytest.raises(WorkspaceError):
        ws.run_shell("echo hi")


def test_a_command_runs_in_the_workspace_with_its_output_and_a_clean_environment(ws, shell_on, monkeypatch):
    monkeypatch.setenv("CODING_SANDBOX_SECRET", "must-not-leak-1234567890")
    result = ws.call("run_shell", {"command": f"echo hello && {PY} -c \"import os; print(sorted(k for k in os.environ if 'SECRET' in k))\""})
    assert result["ok"] is True and result["exit_code"] == 0 and "hello" in result["output"] and "[]" in result["output"]
    assert result["modified"] is False and result["timed_out"] is False
    listing = ws.call("run_shell", {"command": "ls src"})
    assert "app.py" in listing["output"]


def test_a_refused_command_comes_back_with_a_reason_and_does_not_run(ws, shell_on):
    result = ws.call("run_shell", {"command": "curl http://example.com && touch should_not_exist"})
    assert result["blocked"] is True and "no network" in result["error"]
    assert not (ws.root / "should_not_exist").exists()


def test_a_command_that_changes_files_is_reported_as_modifying_and_shows_in_the_diff(ws, shell_on):
    result = ws.call("run_shell", {"command": "echo 'EXTRA = 1' > src/extra.py"})
    assert result["modified"] is True and result["changed_files"] == 1
    assert "src/extra.py" in ws.call("git_diff", {})["files"]


def test_protected_files_changed_by_a_command_are_restored_and_new_ones_removed(ws, shell_on):
    result = ws.call("run_shell", {"command": "echo 'BYPASS = True' > src/shared/auth.py && echo SECRET=1 > .env.local && echo ok > src/fine.py"})
    assert set(result["restored"]) == {"src/shared/auth.py", ".env.local"} and "restored" in result["warning"]
    assert (ws.root / "src/shared/auth.py").read_text().replace("\r\n", "\n") == "SECRET_RULE = True\n" and not (ws.root / ".env.local").exists()
    assert ws.call("git_diff", {})["files"] == ["src/fine.py"]  # the allowed change stays


def test_a_command_that_runs_too_long_is_killed_and_says_so(ws, shell_on):
    result = ws.call("run_shell", {"command": f"{PY} -c \"import time; time.sleep(30)\"", "timeout": 2})
    assert result["timed_out"] is True and result["ok"] is False and result["seconds"] < 20


def test_a_huge_output_is_cut_and_a_failing_command_is_reported(ws, shell_on):
    big = ws.call("run_shell", {"command": f"{PY} -c \"print('x' * 50000)\""})
    assert len(big["output"]) < 8000 and "[output cut]" in big["output"]
    failing = ws.call("run_shell", {"command": f"{PY} -c \"import sys; sys.exit(3)\""})
    assert failing["ok"] is False and failing["exit_code"] == 3


# ------------------------------------------------------------------------------------------------- inside the loop
def run_loop(turns, **kw):
    llm = ScriptedLLM(turns)

    async def go():
        executor = LocalExecutor()
        session = await executor.init(make_tar(REPO))
        try:
            return await controller.run_task(llm, executor, session, "task", "heavy", **{"max_steps": 20, "max_usd": 5.0, "timeout_seconds": 120, **kw})
        finally:
            await executor.close(session)

    return llm, asyncio.run(go())


def test_the_loop_offers_the_shell_only_when_allowed_and_records_every_command(shell_on):
    off, _ = run_loop([turn(tool_call("finish", summary="nothing to do"))], allow_shell=False)
    assert "run_shell" not in {t["function"]["name"] for t in off.seen[0]["tools"]} and "run_shell" not in off.seen[0]["messages"][0]["content"]
    llm, result = run_loop([
        turn(tool_call("run_shell", command="echo one")),
        turn(tool_call("run_shell", command="wget http://x")),
        turn(tool_call("finish", summary="ran two")),
    ], allow_shell=True, shell_timeout=30)
    assert "run_shell" in {t["function"]["name"] for t in llm.seen[0]["tools"]} and "run_shell" in llm.seen[0]["messages"][0]["content"]
    assert result["shell"] is True and [c["command"] for c in result["commands"]] == ["echo one", "wget http://x"]
    assert result["commands"][0]["exit_code"] == 0 and result["commands"][1]["blocked"] is True


def test_a_tool_call_to_a_shell_that_is_not_allowed_is_refused_in_the_controller():
    _, result = run_loop([turn(tool_call("run_shell", command="echo hi")), turn(tool_call("finish", summary="tried"))], allow_shell=False)
    assert result["commands"] == [] and result["shell"] is False


def test_a_command_that_changes_files_makes_earlier_checks_stale(shell_on):
    _, result = run_loop([
        turn(tool_call("read_file", path="src/app.py")),
        turn(tool_call("edit_file", path="src/app.py", old_string="return a + b", new_string="return b + a")),
        turn(tool_call("run_check", check="pytest", paths=["tests"]), tool_call("run_check", check="ruff", paths=["src"])),
        turn(tool_call("run_shell", command="echo 'X = 1' > src/generated.py")),
        turn(tool_call("finish", summary="done")),
    ], allow_shell=True)
    assert "pytest" not in result["checks"] and result["tests_passed"] is False and result["ready_for_review"] is False and result["commands"][0]["modified"] is True


def test_too_many_changed_files_make_the_work_not_ready_even_if_checks_pass(shell_on):
    many = "for i in $(seq 1 30); do echo $i > src/gen_$i.py; done"
    _, result = run_loop([
        turn(tool_call("run_shell", command=many)),
        turn(tool_call("run_check", check="pytest", paths=["tests"]), tool_call("run_check", check="ruff", paths=["src"])),
        turn(tool_call("finish", summary="generated 30 files")),
    ], allow_shell=True)
    assert len(result["files_changed"]) == 30 and result["tests_passed"] and result["ready_for_review"] is False


def test_the_signing_key_helper_returns_the_key_off_linux_and_nothing_when_unset(monkeypatch):
    from src.agents.coding_agent import executor_server

    monkeypatch.delenv("CODING_SANDBOX_SECRET_FD", raising=False)
    monkeypatch.delenv("CODING_SANDBOX_SECRET", raising=False)
    assert executor_server.take_secret() == ""
    if sys.platform.startswith("win"):
        monkeypatch.setenv("CODING_SANDBOX_SECRET", "abc")
        assert executor_server.take_secret() == "abc"  # the re-exec trick is Linux-only; it is checked in the container


def test_the_controller_runs_the_checks_the_model_forgot_on_the_files_that_changed():
    new_test = "def test_new():\n    assert 1 + 1 == 2\n"
    _, result = run_loop([
        turn(tool_call("write_file", path="tests/test_new.py", content=new_test)),
        turn(tool_call("finish", summary="added a test")),  # the model never ran a check
    ])
    assert result["auto_checks"] == ["ruff", "pytest"] and result["tests_passed"] and result["ruff_clean"] and result["ready_for_review"] is True
    assert result["checks"]["pytest"]["ok"] is True


def test_a_forgotten_check_that_fails_is_run_for_real_and_blocks_review():
    broken = "import os\n\n\ndef test_new():\n    assert 1 + 1 == 3\n"  # unused import and a failing assertion
    _, result = run_loop([turn(tool_call("write_file", path="tests/test_bad.py", content=broken)), turn(tool_call("finish", summary="done"))])
    assert result["auto_checks"] == ["ruff", "pytest"] and result["ruff_clean"] is False and result["tests_passed"] is False
    assert result["ready_for_review"] is False


def test_no_automatic_checks_when_the_work_did_not_finish_or_changed_nothing():
    _, nothing = run_loop([turn(tool_call("finish", summary="only looked"))])
    assert nothing["auto_checks"] == [] and nothing["files_changed"] == []
    _, cut_short = run_loop([turn(tool_call("write_file", path="tests/test_x.py", content="def test_x():\n    pass\n"), content="")], max_steps=1)
    assert cut_short["stopped"] == "step_limit" and cut_short["auto_checks"] == []  # an unfinished task is never presented as checked
