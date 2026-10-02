"""Row-Level Security (RLS) AST Transformer via sqlglot.

Automatically parses SQL queries, inspects the AST, and injects tenant and
department scoping predicates into WHERE clauses across all SELECT expressions,
including CTEs, subqueries, and JOINs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
import sqlglot
from sqlglot import exp, parse_one

logger = logging.getLogger(__name__)


def inject_row_level_security(
    sql: str,
    tenant_id: str = "tenant_enterprise",
    department_id: str = "dept_general",
    read_only_dialect: str = "postgres",
) -> str:
    """Inject Row-Level Security (RLS) constraints into a SQL statement AST.

    Traverses all ``exp.Select`` nodes (main queries, subqueries, CTEs) and adds
    ``department_id = :department_id AND tenant_id = :tenant_id`` to each WHERE clause (both must match: OR would let a
    row of the caller's tenant in another department, or of another tenant in the caller's department, through).

    Args:
        sql: The incoming sanitized SQL query string.
        tenant_id: Current user's tenant identifier (e.g. from JWT token).
        department_id: Current user's department identifier (e.g. from JWT token).
        read_only_dialect: SQL dialect for parsing and generating (default: 'postgres').

    Returns:
        str: SQL string with enforced Row-Level Security clauses.

    Raises:
        ValueError: If SQL cannot be parsed.
    """
    if not sql or not sql.strip():
        return sql

    try:
        expression = parse_one(sql, read=read_only_dialect)
    except Exception as exc:
        logger.error("Failed to parse SQL AST for RLS injection: %s", exc)
        raise ValueError(f"RLS AST parsing error: {exc}") from exc

    # Sanitize IDs against unexpected characters
    safe_tenant = str(tenant_id).replace("'", "''")
    safe_dept = str(department_id).replace("'", "''")

    select_nodes = list(expression.find_all(exp.Select))
    if not select_nodes:
        return expression.sql(dialect=read_only_dialect)

    for select in select_nodes:
        # Two AND-ed predicates, appended to any existing WHERE (which is kept as is)
        for column, value in (("department_id", safe_dept), ("tenant_id", safe_tenant)):
            select.where(
                exp.EQ(this=exp.Column(this=exp.to_identifier(column)), expression=exp.Literal.string(value)),
                copy=False,
            )

    secured_sql = expression.sql(dialect=read_only_dialect)
    logger.debug("Injected RLS AST: '%s' -> '%s'", sql[:80], secured_sql[:120])
    return secured_sql
