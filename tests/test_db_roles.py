"""The Database Agent's read-only role: the SQL that creates it, and (with RAG_TEST_DSN) what PostgreSQL really enforces."""
import asyncio
import os

import pytest

from src.shared.db_roles import ensure_readonly_role, readonly_dsn

PASSWORD = "a-long-enough-password-0123456789"


class RecordingPg:
    def __init__(self, existing_role=False, tables=("knowledge_documents",), columns=None):
        self.statements, self.existing_role, self.tables, self.columns = [], existing_role, set(tables), columns or {}

    async def fetch(self, sql, *args, **kw):
        if "current_database" in sql:
            return [{"name": "agentdb"}]
        if "information_schema.columns" in sql:
            return [{"column_name": c} for c in self.columns.get(args[1], ()) if c in args[2]]
        if "pg_roles" in sql:
            return [{"?column?": 1}] if self.existing_role else []
        if "pg_tables" in sql:
            return [{"?column?": 1}] if args[1] in self.tables else []
        raise AssertionError(sql)

    async def execute(self, sql, *args, **kw):
        self.statements.append(sql)


def run(pg, **kw):
    return asyncio.run(ensure_readonly_role(pg, kw.pop("role", "agent_readonly"), kw.pop("password", PASSWORD), kw.pop("tables", ["knowledge_documents"])))


# ---------------------------------------------------------------- the statements
def test_the_role_is_created_locked_down_and_granted_only_the_allowed_tables():
    pg = RecordingPg()
    assert run(pg) == ["knowledge_documents"]
    sql = "\n".join(pg.statements)
    assert 'CREATE ROLE "agent_readonly" LOGIN' in sql and "NOSUPERUSER NOCREATEDB NOCREATEROLE" in sql
    assert "default_transaction_read_only = on" in sql and "statement_timeout = '15s'" in sql
    assert 'REVOKE ALL ON ALL TABLES IN SCHEMA "public" FROM "agent_readonly"' in sql
    assert sql.count("GRANT SELECT") == 1 and 'GRANT SELECT ON TABLE "public"."knowledge_documents"' in sql
    assert "GRANT INSERT" not in sql and "GRANT ALL" not in sql and "langfuse" not in sql


def test_a_second_run_alters_instead_of_creating_and_missing_tables_are_skipped():
    pg = RecordingPg(existing_role=True, tables=())
    assert run(pg) == []
    assert any(s.startswith('ALTER ROLE "agent_readonly" LOGIN PASSWORD') for s in pg.statements)
    assert not any("CREATE ROLE" in s or "GRANT SELECT" in s for s in pg.statements)


def test_names_and_passwords_cannot_inject_sql():
    for bad in ('x"; DROP TABLE users; --', "Role", "role-name", "1abc", ""):
        with pytest.raises(ValueError):
            run(RecordingPg(), role=bad)
    with pytest.raises(ValueError):
        run(RecordingPg(), tables=['t"; DROP TABLE users; --'])
    pg = RecordingPg()
    run(pg, password="quote'inside-a-long-password-123")
    assert "'quote''inside-a-long-password-123'" in pg.statements[0]  # doubled, so it stays inside the literal


def test_a_table_with_tenant_columns_gets_a_row_level_security_policy_for_the_role_only():
    pg = RecordingPg(columns={"knowledge_documents": ["id", "tenant_id", "department_id"]})
    run(pg)
    sql = "\n".join(pg.statements)
    assert 'ALTER TABLE "public"."knowledge_documents" ENABLE ROW LEVEL SECURITY' in sql
    assert 'CREATE POLICY "tenant_scope" ON "public"."knowledge_documents" FOR SELECT TO "agent_readonly"' in sql
    assert "tenant_id::text = current_setting('app.tenant_id', true)" in sql
    assert "department_id::text = current_setting('app.department_id', true)" in sql
    assert "FORCE" not in sql  # the owner (the application) keeps full access for ingestion and maintenance


def test_the_policy_uses_only_the_columns_the_table_has_and_is_recreated_on_every_start():
    pg = RecordingPg(columns={"knowledge_documents": ["tenant_id"]})
    run(pg)
    policy = next(s for s in pg.statements if s.startswith("CREATE POLICY"))
    assert "app.tenant_id" in policy and "app.department_id" not in policy
    assert any(s.startswith("DROP POLICY IF EXISTS") for s in pg.statements)  # idempotent


def test_a_table_without_tenant_columns_gets_no_policy_but_stays_granted():
    pg = RecordingPg(columns={"knowledge_documents": ["id", "note"]})
    assert run(pg) == ["knowledge_documents"]
    assert not any("POLICY" in s or "ROW LEVEL" in s for s in pg.statements)


def test_a_short_password_is_refused():
    with pytest.raises(ValueError, match="16"):
        run(RecordingPg(), password="short")


def test_the_role_dsn_keeps_host_port_and_database_and_encodes_the_password():
    dsn = readonly_dsn("postgresql://admin:secret@postgres:5432/agentdb?sslmode=disable", "agent_readonly", "p@ss:w/rd")
    assert dsn == "postgresql://agent_readonly:p%40ss%3Aw%2Frd@postgres:5432/agentdb?sslmode=disable"


# ---------------------------------------------------------------- what PostgreSQL enforces (needs a real database)
DSN = os.getenv("RAG_TEST_DSN")


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
def test_postgres_itself_refuses_everything_outside_the_allow_list():
    import asyncpg

    from src.shared.postgres_client import PostgresClient

    role = "agent_readonly_test"

    async def scenario():
        admin = PostgresClient(dsn=DSN)
        await admin.connect(min_size=1, max_size=2)
        try:
            await admin.execute("DROP TABLE IF EXISTS dbrole_allowed, dbrole_secret")
            await admin.execute("DROP SCHEMA IF EXISTS dbrole_other CASCADE")
            await admin.execute("CREATE TABLE dbrole_allowed (id int, note text)")
            await admin.execute("CREATE TABLE dbrole_secret (id int, salary int)")
            await admin.execute("CREATE SCHEMA dbrole_other")
            await admin.execute("CREATE TABLE dbrole_other.hidden (id int)")
            await admin.execute("INSERT INTO dbrole_allowed VALUES (1, 'visible')")
            await ensure_readonly_role(admin, role, PASSWORD, ["dbrole_allowed"])
            await ensure_readonly_role(admin, role, PASSWORD, ["dbrole_allowed"])  # idempotent

            reader = PostgresClient(dsn=readonly_dsn(DSN, role, PASSWORD), ensure_pgvector=False)
            await reader.connect(min_size=1, max_size=2)
            try:
                assert [r["note"] for r in await reader.fetch("SELECT note FROM dbrole_allowed")] == ["visible"]
                for forbidden in (
                    "SELECT * FROM dbrole_secret",                 # a table that was not granted
                    "SELECT * FROM dbrole_other.hidden",           # another schema
                    "INSERT INTO dbrole_allowed VALUES (2, 'x')",  # a write, even on the granted table
                    "DELETE FROM dbrole_allowed",
                    "CREATE TABLE dbrole_new (id int)",            # DDL
                    "DROP TABLE dbrole_allowed",
                ):
                    with pytest.raises(asyncpg.PostgresError):
                        await reader.fetch(forbidden) if forbidden.startswith("SELECT") else await reader.execute(forbidden)
                assert (await reader.fetch("SHOW statement_timeout"))[0][0] == "15s"
                assert (await reader.fetch("SHOW default_transaction_read_only"))[0][0] == "on"
            finally:
                await reader.disconnect()
        finally:
            await admin.execute("DROP TABLE IF EXISTS dbrole_allowed, dbrole_secret")
            await admin.execute("DROP SCHEMA IF EXISTS dbrole_other CASCADE")
            await admin.execute(f'DROP OWNED BY "{role}"')
            await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
            await admin.disconnect()

    asyncio.run(scenario())


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
def test_postgres_itself_separates_rows_by_tenant_and_department_even_without_a_where_clause():
    from src.shared.postgres_client import PostgresClient

    role = "agent_readonly_rls_test"

    async def scenario():
        admin = PostgresClient(dsn=DSN)
        await admin.connect(min_size=1, max_size=2)
        try:
            await admin.execute("DROP TABLE IF EXISTS rls_orders")
            await admin.execute("CREATE TABLE rls_orders (id int, tenant_id text, department_id text, amount int)")
            await admin.execute(
                "INSERT INTO rls_orders VALUES (1,'acme','legal',10), (2,'acme','sales',20), (3,'globex','legal',30), (4,'globex','sales',40)"
            )
            await ensure_readonly_role(admin, role, PASSWORD, ["rls_orders"])
            await ensure_readonly_role(admin, role, PASSWORD, ["rls_orders"])  # policies are recreated, not duplicated

            reader = PostgresClient(dsn=readonly_dsn(DSN, role, PASSWORD), ensure_pgvector=False)
            await reader.connect(min_size=1, max_size=2)
            try:
                def ids(rows):
                    return sorted(r["id"] for r in rows)

                everything = "SELECT id FROM rls_orders"  # no WHERE: what a bypassed SQL rewrite would send
                assert ids(await reader.fetch_scoped(everything, tenant_id="acme", department_id="legal")) == [1]
                assert ids(await reader.fetch_scoped(everything, tenant_id="globex", department_id="sales")) == [4]
                assert ids(await reader.fetch_scoped(everything, tenant_id="acme", department_id="nowhere")) == []
                # the caller's own predicate cannot widen what the policy allows
                assert ids(await reader.fetch_scoped("SELECT id FROM rls_orders WHERE tenant_id = 'globex' OR true", tenant_id="acme", department_id="legal")) == [1]
                # no scope at all (a plain connection that never set app.*): the policy fails closed
                assert await reader.fetch(everything) == []
                # the scope lives in one transaction only
                await reader.fetch_scoped(everything, tenant_id="acme", department_id="legal")
                assert await reader.fetch(everything) == []
            finally:
                await reader.disconnect()
            assert ids(await admin.fetch("SELECT id FROM rls_orders")) == [1, 2, 3, 4]  # the owner (the application) is not restricted
        finally:
            await admin.execute("DROP TABLE IF EXISTS rls_orders")
            await admin.execute(f'DROP OWNED BY "{role}"')
            await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
            await admin.disconnect()

    asyncio.run(scenario())
