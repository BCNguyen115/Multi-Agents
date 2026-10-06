"""Alembic: one linear history, the baseline equals what ensure_schema builds, and real PostgreSQL applies it safely."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from src.shared.migrations import ROOT, current_revision, database_url, head_revision, upgrade_to_head

DSN = os.getenv("RAG_TEST_DSN")
HEAD = head_revision()  # every revision is applied by upgrade_to_head, whatever number the newest one has by now


def test_the_history_has_one_head_and_the_baseline_cannot_be_downgraded():
    assert head_revision() == "0008"
    spec = importlib.util.spec_from_file_location("baseline", ROOT / "migrations" / "versions" / "0001_baseline_rag_chunks.py")
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    assert baseline.down_revision is None
    with pytest.raises(RuntimeError, match="knowledge base"):
        baseline.downgrade()


def test_the_driver_url_is_psycopg_and_keeps_credentials_host_and_options():
    assert database_url("postgresql://u:p%40ss@db:5432/app?sslmode=disable") == "postgresql+psycopg://u:p%40ss@db:5432/app?sslmode=disable"
    assert database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"


def test_migration_files_do_not_import_the_running_application():
    # revisions must stay runnable on their own: only alembic and the frozen baseline schema
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        imports = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.startswith(("import ", "from "))]
        assert all(line.split()[1].split(".")[0] in {"alembic", "sqlalchemy", "src"} for line in imports), (path.name, imports)
        assert not any(line.startswith("from src") and "src.ingestion.schema" not in line for line in imports), (path.name, imports)


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def reset():
        engine = create_engine(database_url(DSN))
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS rag_chunks, alembic_version"))
        engine.dispose()

    @staticmethod
    def columns():
        engine = create_engine(database_url(DSN))
        try:
            return {c["name"] for c in inspect(engine).get_columns("rag_chunks")}
        finally:
            engine.dispose()

    def test_a_fresh_database_gets_the_whole_schema_and_a_second_run_changes_nothing(self):
        self.reset()
        assert current_revision(DSN) is None
        assert upgrade_to_head(DSN) == HEAD
        assert {"content", "raw_content", "embedding", "doc_key", "doc_hash", "page", "tenant_id", "tsv"} <= self.columns()
        assert upgrade_to_head(DSN) == HEAD and current_revision(DSN) == HEAD

    def test_full_text_ignores_accents_and_needs_no_english_stemming(self):
        self.reset()
        upgrade_to_head(DSN)
        engine = create_engine(database_url(DSN))
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO rag_chunks (content, raw_content, category) VALUES ('Nghĩa vụ bảo mật kéo dài 5 năm', 'x', 'nda')"))
            hit = connection.execute(text("SELECT count(*) FROM rag_chunks, to_tsquery('simple', immutable_unaccent(:q)) q WHERE tsv @@ q"), {"q": "'bao' | 'mat'"}).scalar()
        engine.dispose()
        assert hit == 1
        self.reset()

    def test_a_database_that_ensure_schema_built_is_adopted_not_rebuilt(self):
        self.reset()
        upgrade_to_head(DSN)
        engine = create_engine(database_url(DSN))
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO rag_chunks (content, raw_content, category) VALUES ('kept', 'kept', 'nda')"))
            connection.execute(text("DROP TABLE alembic_version"))  # as if it had been created by ensure_schema before Alembic existed
        assert upgrade_to_head(DSN) == HEAD
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM rag_chunks WHERE content = 'kept'")).scalar() == 1  # no data lost
        engine.dispose()
        self.reset()

    def test_replicas_starting_together_take_turns(self):
        # separate processes, like backend replicas: the advisory lock in migrations/env.py serialises them
        self.reset()
        env = {**os.environ, "POSTGRES_URL": DSN}
        procs = [
            subprocess.Popen([sys.executable, "-m", "scripts.migrate"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(4)
        ]
        outputs = [p.communicate(timeout=180) for p in procs]
        assert [p.returncode for p in procs] == [0, 0, 0, 0], outputs
        assert all(f"revision {HEAD}" in out for out, _ in outputs)
        engine = create_engine(database_url(DSN))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 1
        engine.dispose()
        self.reset()
