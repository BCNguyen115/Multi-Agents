"""Repositories the coding agent works on (a GitHub link or a git folder under an allowed root), who may add what, and a reviewer's edits of finished work."""
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from asyncpg.exceptions import UniqueViolationError
from fastapi import FastAPI

from src.agents.coding_agent import agent as coding_agent
from src.agents.coding_agent import repos
from src.agents.coding_agent.controller import revise
from src.agents.coding_agent.publisher import Publisher
from src.agents.coding_agent.workspace import MAX_FILE_BYTES, Workspace, WorkspaceError
from src.config import settings
from src.gateway import coding
from src.shared import audit
from src.shared.auth import Principal, acting_as, authenticate

from tests.test_coding_agent import LocalExecutor
from tests.test_coding_workspace import REPO, make_tar

ADMIN = Principal("root", "acme", "ops", frozenset({"admin", "developer", "approver"}), authenticated=True)
DEV = Principal("dev", "acme", "eng", frozenset({"developer"}), authenticated=True)
OTHER = Principal("dev2", "globex", "eng", frozenset({"developer"}), authenticated=True)
VIEWER = Principal("eve", "acme", "eng", frozenset({"viewer"}), authenticated=True)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True, check=True)


class FakeRepoPG:
    """Just enough of the pool for the repository table."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        if sql.startswith("DELETE FROM coding_repos"):
            repo_id, tenant, is_admin, user = args
            row = self.rows.get(repo_id)
            if row and row["tenant_id"] == tenant and (is_admin or row["owner"] == user):
                del self.rows[repo_id]
                return [{"id": repo_id}]
            return []
        if "WHERE id = $1 AND tenant_id = $2" in sql:
            row = self.rows.get(args[0])
            return [row] if row and row["tenant_id"] == args[1] else []
        return sorted((r for r in self.rows.values() if r["tenant_id"] == args[0]), key=lambda r: r["name"].lower())

    async def execute(self, sql: str, *args: Any) -> str:
        repo_id, tenant, owner, name, kind, location, branch = args
        if any(r["tenant_id"] == tenant and r["name"].lower() == name.lower() for r in self.rows.values()):
            raise UniqueViolationError("duplicate")
        self.rows[repo_id] = {"id": repo_id, "tenant_id": tenant, "owner": owner, "name": name, "kind": kind, "location": location, "branch": branch}
        return "INSERT 0 1"


@pytest.fixture()
def folders(tmp_path, monkeypatch):
    """<tmp>/projects holds two git repositories and a plain folder and is the only allowed root; <tmp>/outside is a git repository outside it."""
    root = tmp_path / "projects"
    for name in ("alpha", "beta"):
        repo = root / name
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "init")
    (root / "plain").mkdir()
    (tmp_path / "outside").mkdir()
    git(tmp_path / "outside", "init", "-q")
    monkeypatch.setattr(settings, "CODING_LOCAL_ROOTS", [str(root)])
    monkeypatch.setattr(settings, "CODING_AGENT_ENABLED", True)
    monkeypatch.setattr(settings, "CODING_REPO_URL", "")
    return root


def test_only_git_folders_inside_the_allowed_roots_are_offered_and_accepted(folders, tmp_path):
    found = {f["name"]: f for f in repos.discover()}
    assert set(found) == {"alpha", "beta"} and found["alpha"]["branch"] == "main"  # not the plain folder, not what lies outside the root
    assert repos.allowed_folder(str(folders / "alpha")) == (folders / "alpha").resolve()
    for bad, key in ((str(tmp_path / "outside"), "coding.repo_folder_not_allowed"), (str(folders / "plain"), "coding.repo_not_git"), ("", "coding.repo_bad_folder"),
                     (str(folders / "alpha" / ".." / ".." / "outside"), "coding.repo_folder_not_allowed")):
        with pytest.raises(repos.RepoError) as refused:
            repos.allowed_folder(bad)
        assert refused.value.key == key, bad


def test_a_symlink_cannot_point_a_local_repository_outside_the_roots(folders, tmp_path):
    link = folders / "sneaky"
    try:
        link.symlink_to(tmp_path / "outside", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(repos.RepoError) as refused:
        repos.allowed_folder(str(link))
    assert refused.value.key == "coding.repo_folder_not_allowed"
    assert "sneaky" not in {f["name"] for f in repos.discover()}


def test_adding_a_repository_validates_who_and_what(folders):
    pg = FakeRepoPG()

    async def go() -> None:
        github = await repos.add_repo(pg, tenant_id="acme", owner="dev", is_admin=False, kind="github", location="https://github.com/o/r/", name="Main app", branch="main")
        assert github.kind == "github" and github.location == "https://github.com/o/r"
        for kwargs, key in (
            ({"kind": "github", "location": "https://evil.example/o/r", "name": "x"}, "coding.repo_bad_github"),
            ({"kind": "github", "location": "git@github.com:o/r.git", "name": "x"}, "coding.repo_bad_github"),
            ({"kind": "github", "location": "https://github.com/o/r", "name": "../etc"}, "coding.repo_bad_name"),
            ({"kind": "github", "location": "https://github.com/o/r", "name": "ok", "branch": "a..b"}, "coding.repo_bad_branch"),
            ({"kind": "github", "location": "https://github.com/o/r", "name": "main APP"}, "coding.repo_name_taken"),  # unique per tenant, ignoring case
            ({"kind": "local", "location": str(folders / "alpha"), "name": "alpha"}, "coding.repo_need_admin"),  # a developer cannot open the server's disk
            ({"kind": "ftp", "location": "x", "name": "x"}, "coding.repo_bad_kind"),
        ):
            with pytest.raises(repos.RepoError) as refused:
                await repos.add_repo(pg, tenant_id="acme", owner="dev", is_admin=False, **kwargs)
            assert refused.value.key == key, kwargs
        local = await repos.add_repo(pg, tenant_id="acme", owner="root", is_admin=True, kind="local", location=str(folders / "alpha"), name="alpha")
        assert local.kind == "local" and Path(local.location) == (folders / "alpha").resolve()
        assert [r.name for r in await repos.list_repos(pg, "acme")] == ["alpha", "Main app"]
        assert await repos.list_repos(pg, "globex") == []  # another tenant sees none of them
        assert await repos.resolve(pg, "globex", github.id) is None and (await repos.resolve(pg, "acme", github.id)).name == "Main app"
        assert await repos.remove_repo(pg, tenant_id="acme", user_id="someone", is_admin=False, repo_id=github.id) is False  # not the owner
        assert await repos.remove_repo(pg, tenant_id="acme", user_id="dev", is_admin=False, repo_id=github.id) is True

    asyncio.run(go())


def test_the_default_comes_from_the_settings_and_a_local_folder_is_rechecked_when_used(folders, monkeypatch):
    monkeypatch.setattr(settings, "CODING_REPO_URL", "https://github.com/o/app.git")
    monkeypatch.setattr(settings, "CODING_REPO_BRANCH", "")
    default = repos.default_repo()
    assert default and default.id == repos.DEFAULT_ID and default.name == "app" and default.kind == "github"
    assert asyncio.run(repos.resolve(FakeRepoPG(), "acme", "")) == default
    assert isinstance(repos.publisher_for(default), Publisher)
    assert isinstance(repos.publisher_for(repos.Repo("r1", "alpha", "local", str(folders / "alpha"), "", "acme", "root")), Publisher)
    with pytest.raises(repos.RepoError):  # a folder that is no longer under the roots can no longer be worked on
        repos.publisher_for(repos.Repo("r2", "x", "local", str(folders.parent / "outside"), "", "acme", "root"))


# ------------------------------------------------------------------------------------------------- the endpoints
def client(pg: Any, who: Principal) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(coding.router)
    app.state.pg_client = pg
    app.dependency_overrides[authenticate] = lambda: who
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.fixture()
def audited(monkeypatch):
    recorded: list = []

    async def record(action, target="", outcome="ok", detail=None, *, principal=None, required=False):
        recorded.append((action, required))
        return True

    monkeypatch.setattr(audit, "record", record)
    return recorded


def test_the_repository_endpoints_follow_the_roles_and_audit_every_change(folders, audited):
    pg = FakeRepoPG()

    async def go() -> None:
        async with client(pg, DEV) as dev:
            added = await dev.post("/api/coding/repos", json={"kind": "github", "location": "https://github.com/o/r", "name": "app"})
            assert added.status_code == 201 and added.json()["kind"] == "github"
            assert (await dev.post("/api/coding/repos", json={"kind": "local", "location": str(folders / "alpha"), "name": "a"})).status_code == 422
            assert (await dev.get("/api/coding/repos/discover")).status_code == 403
            listing = (await dev.get("/api/coding/repos")).json()
            assert [r["name"] for r in listing["repos"]] == ["app"] and listing["repos"][0]["mine"] is True and listing["can_add_local"] is False
            repo_id = added.json()["id"]
        async with client(pg, ADMIN) as admin:
            found = (await admin.get("/api/coding/repos/discover")).json()
            assert {f["name"] for f in found["folders"]} == {"alpha", "beta"}
            local = await admin.post("/api/coding/repos", json={"kind": "local", "location": str(folders / "beta"), "name": "beta"})
            assert local.status_code == 201
            assert (await admin.post("/api/coding/repos", json={"kind": "local", "location": "/etc", "name": "etc"})).status_code == 422
            assert (await admin.delete(f"/api/coding/repos/{repo_id}")).status_code == 204  # an administrator may remove anyone's
        async with client(pg, OTHER) as other:
            assert (await other.get("/api/coding/repos")).json()["repos"] == []  # another tenant
            assert (await other.delete(f"/api/coding/repos/{local.json()['id']}")).status_code == 404
        async with client(pg, VIEWER) as viewer:
            assert (await viewer.get("/api/coding/repos")).status_code == 403
            assert (await viewer.post("/api/coding/repos", json={"kind": "github", "location": "https://github.com/o/r", "name": "x"})).status_code == 403

    asyncio.run(go())
    assert [a for a, _ in audited].count("coding.repo_add") == 2 and "coding.repo_remove" in [a for a, _ in audited]
    assert all(required for _, required in audited)  # no record, no change


def test_a_task_runs_on_the_repository_chosen_in_the_chat(folders, monkeypatch):
    pg = FakeRepoPG()
    queued: list = []

    async def enqueue(_pg, kind, principal, payload, data=None):
        queued.append(payload)
        return "job1"

    monkeypatch.setattr(coding_agent.jobs, "enqueue", enqueue)

    async def go() -> list[dict[str, Any]]:
        repo = await repos.add_repo(pg, tenant_id="acme", owner="dev", is_admin=False, kind="github", location="https://github.com/o/r", name="app")
        agent = coding_agent.CodingAgent(pg_client=pg)
        out = []
        for chosen in (repo.id, "does_not_exist", ""):
            repos.selected_repo.set(chosen)
            with acting_as(DEV):
                out.append(json.loads(await agent.process_request("fix it", "s1")))
        return out

    chosen, missing, none = asyncio.run(go())
    assert chosen["job_id"] == "job1" and queued[0]["repo"]["name"] == "app" and queued[0]["repo"]["location"] == "https://github.com/o/r"
    assert missing["type"] == "error" and none["type"] == "error" and len(queued) == 1  # a missing repository and no default queue nothing


# ------------------------------------------------------------------------------------------------- a reviewer edits the finished work
@pytest.fixture()
def finished(tmp_path):
    """A workspace holding the agent's change: src/app.py edited."""
    workspace = Workspace(tmp_path / "w")
    workspace.root.mkdir()
    workspace.load_tar(make_tar(REPO))
    workspace.call("read_file", {"path": "src/app.py"})
    assert "error" not in workspace.call("edit_file", {"path": "src/app.py", "old_string": "return a + b", "new_string": "return b + a"})
    return workspace


def test_the_diff_editor_gets_what_each_file_was_and_is(finished):
    pairs = finished.call("git_files", {})
    assert pairs["truncated"] is False and [p["path"] for p in pairs["files"]] == ["src/app.py"]
    entry = pairs["files"][0]
    assert entry["status"] == "modified" and "return a + b" in entry["before"] and "return b + a" in entry["after"] and entry["protected"] is False
    finished.call("write_file", {"path": "src/new.py", "content": "X = 1\n"})
    finished.call("read_file", {"path": "tests/test_app.py"})
    finished.call("delete_file", {"path": "tests/test_app.py"})
    by_path = {p["path"]: p for p in finished.call("git_files", {})["files"]}
    assert by_path["src/new.py"]["status"] == "added" and by_path["src/new.py"]["before"] == ""
    assert by_path["tests/test_app.py"]["status"] == "deleted" and by_path["tests/test_app.py"]["after"] == ""


def test_a_reviewer_edit_is_limited_to_files_of_the_change_and_never_to_protected_ones(finished):
    assert finished.review_put("src/app.py", "def add(a, b):\n    return a + b + 0\n")["path"] == "src/app.py"
    assert "a + b + 0" in finished.call("git_files", {})["files"][0]["after"]
    for path in ("src/shared/auth.py", ".env", "src/other.py", "../x.py"):  # protected, protected, not part of the change, outside the workspace
        with pytest.raises((WorkspaceError, ValueError)):
            finished.review_put(path, "x = 1\n")
    with pytest.raises(WorkspaceError):
        finished.review_put("src/app.py", "x" * (MAX_FILE_BYTES + 1))
    assert "error" in finished.call("review_put", {"path": "src/app.py", "content": "x"})  # not a tool the model can call


class ReviewExecutor(LocalExecutor):
    async def review_put(self, session: str, path: str, content: str) -> dict[str, Any]:
        try:
            return self.workspaces[session].review_put(path, content)
        except (WorkspaceError, ValueError) as exc:
            return {"error": str(exc)}


def test_edits_make_the_checks_run_again_and_the_work_is_judged_on_the_new_results():
    async def go() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        executor = ReviewExecutor()
        session = await executor.init(make_tar(REPO))
        try:
            await executor.call(session, "read_file", {"path": "src/app.py"})
            await executor.call(session, "edit_file", {"path": "src/app.py", "old_string": "return a + b", "new_string": "return b + a"})
            good = await revise(executor, session, {"src/app.py": "def add(a, b):\n    return b + a\n"})
            broken = await revise(executor, session, {"src/app.py": "def add(a, b):\n    return 0\n"})  # the reviewer's edit breaks the test
            refused = await revise(executor, session, {"src/shared/auth.py": "X = 2\n", "src/app.py": "def add(a, b):\n    return a + b\n"})
            return good, broken, refused
        finally:
            await executor.close(session)

    good, broken, refused = asyncio.run(go())
    assert good["ready_for_review"] is True and good["tests_passed"] is True and good["files_changed"] == ["src/app.py"]
    assert good["files_detail"][0]["after"].endswith("return b + a\n")
    assert broken["ready_for_review"] is False and broken["tests_passed"] is False  # judged on the re-run, not on the agent's earlier results
    assert set(refused["errors"]) == {"src/shared/auth.py"}  # one refused edit and nothing is evaluated
