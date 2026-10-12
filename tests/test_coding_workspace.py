"""The coding agent's hands: what a workspace lets a model read, write and run. These checks are the security boundary, so they are tested
as attacks, not as features."""
import io
import tarfile
from pathlib import Path

import pytest

from src.agents.coding_agent import policy
from src.agents.coding_agent.workspace import MAX_CHANGED_FILES, Workspace


def make_tar(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


REPO = {
    "src/app.py": "def add(a, b):\n    return a + b\n",
    "tests/test_app.py": "from src.app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "src/shared/auth.py": "SECRET_RULE = True\n",
    ".env": "OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnop1234\n",
    "migrations/001.py": "pass\n",
}


@pytest.fixture()
def ws(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path / "w")
    workspace.root.mkdir()
    workspace.load_tar(make_tar(REPO))
    return workspace


def test_the_agent_edits_a_normal_file_and_gets_the_diff_back(ws):
    ws.call("read_file", {"path": "src/app.py"})
    out = ws.call("write_file", {"path": "src/app.py", "content": "def add(a, b):\n    return b + a\n"})
    assert out["changed_files"] == 1 and out["created"] is False
    diff = ws.call("git_diff", {})
    assert diff["files"] == ["src/app.py"] and "-    return a + b" in diff["patch"] and "+    return b + a" in diff["patch"]


@pytest.mark.parametrize("path", [".env", "src/shared/auth.py", "migrations/001.py", ".github/workflows/ci.yml", "Dockerfile", "docker-compose.yml",
                                  "requirements.txt", "frontend/package.json", "src/agents/coding_agent/policy.py", "scripts/make_token.py", ".git/config"])
def test_protected_files_can_be_neither_written_nor_deleted(ws, path):
    assert "protected" in ws.call("write_file", {"path": path, "content": "x"})["error"]
    assert "protected" in ws.call("delete_file", {"path": path})["error"]
    assert ws.call("git_diff", {})["files"] == []


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "C:\\Windows\\win.ini", "src/../../x", "", "a\x00b", "\\root"])
def test_paths_cannot_leave_the_workspace(ws, path):
    for tool, args in (("read_file", {"path": path}), ("write_file", {"path": path, "content": "x"}), ("delete_file", {"path": path})):
        assert "error" in ws.call(tool, args)


def test_secrets_are_not_readable_or_listed(ws):
    assert "not readable" in ws.call("read_file", {"path": ".env"})["error"]
    assert ".env" not in ws.call("list_files", {})["files"]
    assert not any("sk-or-v1" in hit["text"] for hit in ws.call("search", {"pattern": "sk-or-v1"})["hits"])


def test_a_tarball_cannot_plant_links_or_escape(tmp_path):
    link = tarfile.TarInfo("evil")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.addfile(link)
        info = tarfile.TarInfo("ok.txt")
        info.size = 2
        archive.addfile(info, io.BytesIO(b"hi"))
    plain = Workspace(tmp_path / "w2")
    plain.root.mkdir()
    plain.load_tar(buffer.getvalue())
    assert not (plain.root / "evil").exists() and (plain.root / "ok.txt").read_text() == "hi"  # the symlink was skipped

    escaping = io.BytesIO()
    with tarfile.open(fileobj=escaping, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    other = Workspace(tmp_path / "w3")
    other.root.mkdir()
    with pytest.raises(ValueError):
        other.load_tar(escaping.getvalue())  # the parent path is refused outright
    assert not (tmp_path / "escape.txt").exists()


def test_only_the_named_checks_run_and_with_no_shell(ws):
    assert ws.call("run_check", {"check": "pytest", "paths": ["tests"]})["ok"] is True
    for bad in ({"check": "bash"}, {"check": "pytest; rm -rf /"}, {"check": "pytest", "paths": ["../.."]},
                {"check": "pytest", "paths": ["tests"], "keyword": "x; echo hi"}, {"check": "ruff", "keyword": "x"}, {"check": "pytest", "paths": ["nope"]}):
        assert "error" in ws.call("run_check", bad), bad


def test_a_failing_test_is_reported_not_hidden(ws):
    ws.call("read_file", {"path": "src/app.py"})
    ws.call("write_file", {"path": "src/app.py", "content": "def add(a, b):\n    return 0\n"})
    result = ws.call("run_check", {"check": "pytest", "paths": ["tests"]})
    assert result["ok"] is False and result["exit_code"] == 1 and "assert" in result["output"]


def test_the_checks_cannot_see_the_containers_secrets(ws, monkeypatch):
    monkeypatch.setenv("SANDBOX_SECRET", "super-secret-value")
    ws.call("write_file", {"path": "tests/test_env.py", "content": "import os\n\n\ndef test_env():\n    assert 'SANDBOX_SECRET' not in os.environ\n"})
    assert ws.call("run_check", {"check": "pytest", "paths": ["tests/test_env.py"]})["ok"] is True


def test_one_change_cannot_grow_past_the_file_limit(ws):
    for number in range(MAX_CHANGED_FILES):
        assert "error" not in ws.call("write_file", {"path": f"src/mod_{number}.py", "content": "x = 1\n"})
    assert "too many changed files" in ws.call("write_file", {"path": "src/one_more.py", "content": "x = 1\n"})["error"]
    assert not (ws.root / "src/one_more.py").exists()


def test_credentials_in_a_patch_are_found_by_kind_only():
    patch = "diff --git a/x.py b/x.py\n+++ b/x.py\n+KEY = 'sk-or-v1-abcdefghijklmnop1234'\n+TOKEN='ghp_" + "a" * 36 + "'\n-old = 1\n"
    assert policy.find_secrets(patch) == ["openrouter-key", "github-token"]
    assert policy.find_secrets("+++ b/x\n+ordinary = 1\n") == []
    assert "sk-or" not in str(policy.find_secrets(patch))
    assert policy.files_in_patch("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n") == ["src/a.py"]


def test_an_existing_file_is_never_changed_blind(ws):
    for tool, args in (("write_file", {"path": "src/app.py", "content": "x = 1\n"}),
                       ("edit_file", {"path": "src/app.py", "old_string": "a + b", "new_string": "b + a"})):
        assert "read src/app.py completely" in ws.call(tool, args)["error"]
    assert ws.call("git_diff", {})["files"] == []
    assert "error" not in ws.call("write_file", {"path": "src/brand_new.py", "content": "x = 1\n"})  # a new file needs no reading
    ws.call("read_file", {"path": "./SRC/app.py"})  # './' and case do not matter
    assert "error" not in ws.call("edit_file", {"path": "src/app.py", "old_string": "a + b", "new_string": "b + a"})


def test_edit_file_replaces_one_exact_unique_piece_and_says_why_when_it_cannot(ws):
    ws.call("read_file", {"path": "src/app.py"})
    ws.call("write_file", {"path": "src/dup.py", "content": "x = 1\ny = 1\n"})
    assert "was not found" in ws.call("edit_file", {"path": "src/app.py", "old_string": "a - b", "new_string": "a"})["error"]
    assert "matches 2 places" in ws.call("edit_file", {"path": "src/dup.py", "old_string": "= 1", "new_string": "= 2"})["error"]
    assert ws.call("edit_file", {"path": "src/dup.py", "old_string": "= 1", "new_string": "= 2", "replace_all": True})["replaced"] == 2
    assert "must not be empty" in ws.call("edit_file", {"path": "src/app.py", "old_string": "", "new_string": "x"})["error"]
    assert "identical" in ws.call("edit_file", {"path": "src/app.py", "old_string": "a", "new_string": "a"})["error"]
    assert "no such file" in ws.call("edit_file", {"path": "src/none.py", "old_string": "a", "new_string": "b"})["error"]
    assert "protected" in ws.call("edit_file", {"path": "src/shared/auth.py", "old_string": "True", "new_string": "False"})["error"]
    assert ws.call("edit_file", {"path": "src/app.py", "old_string": "return a + b", "new_string": "return b + a"})["replaced"] == 1
    assert "return b + a" in ws.call("git_diff", {})["patch"]


def test_a_file_read_only_in_part_cannot_be_overwritten(ws):
    big = "# " + "x" * 220_000 + "\n"  # under the write limit, over the read limit
    (ws.root / "src" / "big.py").write_text(big)
    assert ws.call("read_file", {"path": "src/big.py"})["truncated"] is True
    assert "read src/big.py completely" in ws.call("write_file", {"path": "src/big.py", "content": "x = 1\n"})["error"]
