"""Async engine + session factory.

The engine is created lazily on first ``get_engine()`` so importing the
``db`` package doesn't require a reachable Postgres (e.g. for ``alembic``
script discovery).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import get_config


def _async_dsn(sync_dsn: str) -> str:
    """Convert ``postgresql://`` → ``postgresql+asyncpg://`` for SQLAlchemy."""
    if sync_dsn.startswith("postgresql+asyncpg://"):
        return sync_dsn
    if sync_dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + sync_dsn[len("postgresql://"):]
    if sync_dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + sync_dsn[len("postgres://"):]
    return sync_dsn


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    cfg = get_config()
    db = cfg.database
    return create_async_engine(
        _async_dsn(db.dsn),
        pool_size=db.pool_min,
        max_overflow=max(0, db.pool_max - db.pool_min),
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields a session, commits on success, rolls back on error."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Call from shutdown hooks."""
    if get_engine.cache_info().currsize:
        engine = get_engine()
        await engine.dispose()
