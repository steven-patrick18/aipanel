"""Alembic environment.

DSN resolution order:
1. ``ALEMBIC_DATABASE_URL`` env var (allows running offline)
2. The aipanel config loader (reads /etc/aipanel/aipanel.conf + secrets.env)
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make src/ importable when alembic is launched from panel/backend/.
HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aipanel.db.base import Base  # noqa: E402
import aipanel.db.models           # noqa: E402,F401  - register every model

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_dsn() -> str:
    env_dsn = os.environ.get("ALEMBIC_DATABASE_URL")
    if env_dsn:
        return env_dsn
    from aipanel.config import get_config
    return get_config().database.dsn


def run_migrations_offline() -> None:
    url = _resolve_dsn()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _resolve_dsn()
    cfg_dict = config.get_section(config.config_ini_section, {})
    cfg_dict["sqlalchemy.url"] = url
    connectable = engine_from_config(
        cfg_dict,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
