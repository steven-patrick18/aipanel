"""Declarative base for all SQLAlchemy ORM models.

Single ``Base`` class shared by every model file under ``db.models.*`` so
Alembic autogenerate sees them all on ``Base.metadata``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class Base(DeclarativeBase):
    """Application-wide ORM base. Concrete tables live under ``db.models``."""
