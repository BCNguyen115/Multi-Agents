"""The coding agent on a LOCAL folder instead of a GitHub link: it sees the working tree (uncommitted work included, ignored files not), and
publishing creates a branch in that repository without touching its working tree or its checked-out branch."""
import asyncio
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from src.agents.coding_agent.publisher import Publisher, PublishError
from src.agents.coding_agent.workspace import Workspace


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture()
def folder(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "work")
    (repo / ".gitignore").write_bytes(b".env\nbig.bin\n")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_bytes(b"def add(a, b):\n    return a + b\n")
    (repo / "src" / "util.py").write_bytes(b"VALUE = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "committed state")
    # what a developer has in progress: an uncommitted edit, a new file, an ignored secret, a deleted tracked file
    (repo / "src" / "app.py").write_bytes(b"def add(a, b):\n    # work in progress\n    return a + b\n")
    (repo / "src" / "new_feature.py").write_bytes(b"FEATURE = True\n")
    (repo / ".env").write_bytes(b"OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnop1234\n")
    (repo / "big.bin").write_bytes(b"x" * 10)
    (repo / "personal.pdf").write_bytes(b"%PDF-1.4\0\0binary content")  # untracked, not ignored: a personal document must not travel
    (repo / "src" / "util.py").unlink()
    return repo


def names(tar: bytes) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as archive:
        return {m.name for m in archive if m.isfile()}


def test_the_sandbox_starts_from_the_working_tree_not_only_from_what_was_committed(folder):
    publisher = Publisher(str(folder), "", "", local=True)
    tar = asyncio.run(publisher.make_archive())
    assert publisher.target == "local" and "src/new_feature.py" in names(tar) and "src/app.py" in names(tar)
    assert ".env" not in names(tar) and "big.bin" not in names(tar)  # ignored files never leave the folder
    assert "personal.pdf" not in names(tar)  # nor do binary files, ignored or not
    assert "src/util.py" not in names(tar)  # deleted in the working tree
    with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as archive:
        assert b"work in progress" in archive.extractfile("src/app.py").read()


def test_head_only_mode_ignores_uncommitted_work(folder):
    tar = asyncio.run(Publisher(str(folder), "", "", local=True, snapshot=False).make_archive())
    assert "src/util.py" in names(tar) and "src/new_feature.py" not in names(tar)


def make_patch(tmp_path: Path, tar: bytes) -> str:
    workspace = Workspace(tmp_path / "ws")
    workspace.root.mkdir()
    workspace.load_tar(tar)
    workspace.call("read_file", {"path": "src/app.py"})
    workspace.call("edit_file", {"path": "src/app.py", "old_string": "return a + b", "new_string": "return b + a"})
    return workspace.call("git_diff", {})["patch"]


def test_publishing_creates_a_branch_with_the_snapshot_and_the_agents_change_and_leaves_the_folder_alone(folder, tmp_path):
    publisher = Publisher(str(folder), "", "", local=True)
    patch = make_patch(tmp_path, asyncio.run(publisher.make_archive()))
    before = {"branch": git(folder, "branch", "--show-current").strip(), "status": git(folder, "status", "--porcelain"),
              "app": (folder / "src" / "app.py").read_bytes()}
    published = asyncio.run(publisher.publish(patch, "Swap the operands", "body", "abcdef1234"))
    assert published == {"branch": "agent/abcdef12-swap-the-operands", "pr_url": "", "local": True}
    branch = published["branch"]
    # the folder is exactly as the developer left it
    assert git(folder, "branch", "--show-current").strip() == before["branch"] == "work"
    assert git(folder, "status", "--porcelain") == before["status"] and (folder / "src" / "app.py").read_bytes() == before["app"]
    # the branch: committed state -> snapshot of the working tree -> the agent's change alone
    log = git(folder, "log", "--format=%s", branch).splitlines()
    assert log[:2] == ["Swap the operands", "Working tree at the time of the coding task (uncommitted changes)"] and log[2] == "committed state"
    only_agent = git(folder, "diff", f"{branch}~1", branch)
    assert "+    return b + a" in only_agent and "new_feature" not in only_agent  # the snapshot's own changes are not in the agent's diff
    assert git(folder, "show", f"{branch}~1:src/new_feature.py").strip() == "FEATURE = True"  # the snapshot carries the uncommitted file
    assert ".env" not in git(folder, "ls-tree", "-r", "--name-only", branch)


def test_a_patch_made_before_the_folder_changed_is_refused_with_a_plain_reason(folder, tmp_path):
    publisher = Publisher(str(folder), "", "", local=True)
    patch = make_patch(tmp_path, asyncio.run(publisher.make_archive()))
    (folder / "src" / "app.py").write_bytes(b"def add(a, b):\n    return a * b\n")  # edited again while the task was being reviewed
    with pytest.raises(PublishError, match="files changed since the task ran"):
        asyncio.run(publisher.publish(patch, "Swap", "b", "abcdef1234"))
    assert "agent/" not in git(folder, "branch", "--list")


def test_the_same_safety_net_applies_and_a_wrong_folder_is_rejected(folder, tmp_path):
    publisher = Publisher(str(folder), "", "", local=True)
    protected = "diff --git a/src/shared/auth.py b/src/shared/auth.py\n--- a/src/shared/auth.py\n+++ b/src/shared/auth.py\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(PublishError, match="protected"):
        asyncio.run(publisher.publish(protected, "x", "b", "abcdef1234"))
    with pytest.raises(PublishError, match="git repository folder"):
        Publisher(str(tmp_path / "missing"), "", "", local=True)
    (tmp_path / "plain").mkdir()
    with pytest.raises(PublishError, match="git repository folder"):
        Publisher(str(tmp_path / "plain"), "", "", local=True)
    assert Publisher("https://github.com/o/r.git", "t").target == "github" and Publisher("https://github.com/o/r.git", "t").base == "main"
