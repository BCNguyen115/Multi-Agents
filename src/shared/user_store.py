"""Self-registered accounts (table ``app_users``). Administrator-made accounts stay in ``AUTH_USERS``.

Usernames are stored lower-case: ``Alice`` and ``alice`` are the same account. A user row has the same shape the login code
already reads from ``AUTH_USERS`` entries (``username``, ``password_hash``, ``roles``, ``tenant_id``, ``department_id``),
plus ``display_name`` and ``recovery_hash`` (the scrypt hash of the recovery key shown once at sign-up; the key itself is never stored).
"""

from __future__ import annotations

from typing import Any, Optional


async def get_user(pg: Any, username: str) -> Optional[dict[str, Any]]:
    rows = await pg.fetch(
        "SELECT username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id, disabled FROM app_users WHERE username = $1",
        username.lower(),
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "username": row["username"],
        "display_name": row["display_name"],
        "password_hash": row["password_hash"],
        "recovery_hash": row["recovery_hash"],
        "roles": list(row["roles"] or []),
        "tenant_id": row["tenant_id"],
        "department_id": row["department_id"],
        "disabled": bool(row["disabled"]),
    }


async def list_users(pg: Any) -> list[dict[str, Any]]:
    """Every self-registered account for the administration page (never the password or recovery hashes)."""
    rows = await pg.fetch("SELECT username, display_name, roles, tenant_id, department_id, disabled, created_at FROM app_users ORDER BY created_at")
    return [
        {
            "username": r["username"], "display_name": r["display_name"], "roles": list(r["roles"] or []),
            "tenant_id": r["tenant_id"], "department_id": r["department_id"], "disabled": bool(r["disabled"]), "created_at": r["created_at"],
        }
        for r in rows
    ]


async def upsert_sso_user(pg: Any, username: str, display_name: str, tenant_id: str, department_id: str) -> Optional[dict[str, Any]]:
    """The account of someone who signed in through the identity provider: created in the pending tenant on the first sign-in, afterwards
    only the display name follows the provider (tenant, roles and lock stay what an administrator set). ``None`` when the name belongs
    to a password account, which an SSO sign-in must never take over."""
    rows = await pg.fetch(
        "INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) "
        "VALUES ($1, $2, 'sso', '', '{}', $3, $4) "
        "ON CONFLICT (username) DO UPDATE SET display_name = EXCLUDED.display_name WHERE app_users.password_hash = 'sso' "
        "RETURNING username, display_name, roles, tenant_id, department_id, disabled",
        username.lower(), display_name[:64], tenant_id, department_id,
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "username": r["username"], "display_name": r["display_name"], "roles": list(r["roles"] or []),
        "tenant_id": r["tenant_id"], "department_id": r["department_id"], "disabled": bool(r["disabled"]),
    }


async def update_user(
    pg: Any, username: str, *, tenant_id: Optional[str] = None, department_id: Optional[str] = None,
    roles: Optional[list[str]] = None, disabled: Optional[bool] = None,
) -> bool:
    """Change only the given fields (``None`` = leave as is); ``False`` if no such account."""
    rows = await pg.fetch(
        "UPDATE app_users SET tenant_id = COALESCE($2, tenant_id), department_id = COALESCE($3, department_id), "
        "roles = COALESCE($4::text[], roles), disabled = COALESCE($5, disabled) WHERE username = $1 RETURNING username",
        username.lower(), tenant_id, department_id, roles, disabled,
    )
    return bool(rows)


async def move_users(pg: Any, tenant_id: str, department_id: Optional[str], to_tenant: str, to_department: str) -> list[str]:
    """Move every self-registered account of a department (or, with ``department_id=None``, of a whole tenant) to another one; returns who moved."""
    rows = await pg.fetch(
        "UPDATE app_users SET tenant_id = $3, department_id = $4 WHERE tenant_id = $1 AND ($2::text IS NULL OR department_id = $2) RETURNING username",
        tenant_id, department_id, to_tenant, to_department,
    )
    return [r["username"] for r in rows]


async def create_user(
    pg: Any, username: str, display_name: str, password_hash: str, recovery_hash: str, tenant_id: str, department_id: str
) -> bool:
    """Insert a new account with NO roles; ``False`` when the username is already taken (decided by the primary key, race-free)."""
    rows = await pg.fetch(
        "INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) "
        "VALUES ($1, $2, $3, $4, '{}', $5, $6) ON CONFLICT (username) DO NOTHING RETURNING username",
        username.lower(), display_name, password_hash, recovery_hash, tenant_id, department_id,
    )
    return bool(rows)


async def set_password(pg: Any, username: str, password_hash: str, recovery_hash: Optional[str] = None) -> bool:
    """New password for an existing account; a reset also passes a fresh ``recovery_hash`` (the old key is spent). ``False`` if no such account."""
    if recovery_hash is None:
        rows = await pg.fetch("UPDATE app_users SET password_hash = $2 WHERE username = $1 RETURNING username", username.lower(), password_hash)
    else:
        rows = await pg.fetch(
            "UPDATE app_users SET password_hash = $2, recovery_hash = $3 WHERE username = $1 RETURNING username",
            username.lower(), password_hash, recovery_hash,
        )
    return bool(rows)
