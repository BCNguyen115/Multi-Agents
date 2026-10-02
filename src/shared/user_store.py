"""Self-registered accounts (table ``app_users``). Administrator-made accounts stay in ``AUTH_USERS``.

Usernames are stored lower-case: ``Alice`` and ``alice`` are the same account. A user row has the same shape the login code
already reads from ``AUTH_USERS`` entries (``username``, ``password_hash``, ``roles``, ``tenant_id``, ``department_id``),
plus ``display_name`` and ``recovery_hash`` (the scrypt hash of the recovery key shown once at sign-up; the key itself is never stored).
"""

from __future__ import annotations

from typing import Any, Optional


async def get_user(pg: Any, username: str) -> Optional[dict[str, Any]]:
    rows = await pg.fetch(
        "SELECT username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id FROM app_users WHERE username = $1",
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
    }


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
