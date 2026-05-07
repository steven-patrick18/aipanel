"""Local-dev: create the first tenant + admin user against dev Postgres.

Usage (from repo root, with the panel backend venv active and
AIPANEL_CONF / AIPANEL_SECRETS exported)::

    python dev/bootstrap_admin.py --tenant Acme \\
        --email admin@acme.local --password change-me-strong

Idempotent: re-running with the same email updates the password hash
and re-asserts the admin role.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from getpass import getpass

# Make the panel backend importable when running from repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
PANEL_SRC = os.path.normpath(os.path.join(HERE, "..", "panel", "backend", "src"))
if PANEL_SRC not in sys.path:
    sys.path.insert(0, PANEL_SRC)


async def _bootstrap(dsn: str, tenant_name: str, email: str, pw_hash: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT id FROM tenants WHERE name = $1", tenant_name,
        )
        if row:
            tenant_id = row["id"]
            print(f"Tenant {tenant_name!r} already exists ({tenant_id})")
        else:
            tenant_id = await conn.fetchval(
                "INSERT INTO tenants (name) VALUES ($1) RETURNING id",
                tenant_name,
            )
            print(f"Created tenant {tenant_name!r} ({tenant_id})")

        user_id = await conn.fetchval(
            """
            INSERT INTO users (tenant_id, email, password_hash, role)
            VALUES ($1, $2, $3, 'admin')
            ON CONFLICT (email) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    role          = 'admin'
            RETURNING id
            """,
            tenant_id, email, pw_hash,
        )
    finally:
        await conn.close()

    print(f"Admin user ready: {email} ({user_id})")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant", default="Default")
    p.add_argument("--email", required=False)
    p.add_argument("--password", required=False)
    args = p.parse_args()

    email = (args.email or input("Admin email: ")).strip().lower()
    if "@" not in email:
        print("Email looks malformed", file=sys.stderr)
        return 2
    password = args.password or getpass("Admin password (>=8 chars): ")
    if len(password) < 8:
        print("Password must be >= 8 chars", file=sys.stderr)
        return 2

    # Default to the dev config files if the caller didn't override them.
    os.environ.setdefault(
        "AIPANEL_CONF",
        os.path.normpath(os.path.join(HERE, "aipanel.dev.conf")),
    )
    os.environ.setdefault(
        "AIPANEL_SECRETS",
        os.path.normpath(os.path.join(HERE, "secrets.dev.env")),
    )

    from aipanel.auth.jwt import hash_password
    from aipanel.config import get_config

    cfg = get_config()
    pw_hash = hash_password(password)
    asyncio.run(_bootstrap(cfg.database.dsn, args.tenant, email, pw_hash))

    print()
    print("Sign in at http://127.0.0.1:8055/login once Vite is running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
