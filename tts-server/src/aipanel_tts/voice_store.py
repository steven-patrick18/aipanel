"""Postgres-backed registry for cloned voices.

Filesystem layout (mirrored in DB):

    /var/lib/aipanel/voices/<voice_id>/ref.wav
    /var/lib/aipanel/voices/<voice_id>/ref_text.txt

The ``voices`` table from migration 001 keeps name, sample_path, embedding_path,
status, and tenant_id. We treat ``ref.wav`` as both the ``sample_path`` and
the ``embedding_path`` (F5-TTS doesn't surface a separate embedding vector).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog

if TYPE_CHECKING:                                            # pragma: no cover
    pass  # psycopg imported lazily so unit tests don't need it on PATH

log = structlog.get_logger().bind(component="voice_store")


@dataclass(frozen=True)
class VoiceRecord:
    voice_id: UUID
    tenant_id: UUID
    name: str
    sample_path: str
    embedding_path: str
    status: str


class VoiceStore:
    def __init__(self, db_dsn: str | None) -> None:
        self.db_dsn = db_dsn

    # ------------------------------------------------------------------
    # Mutating ops
    # ------------------------------------------------------------------

    def create(
        self,
        tenant_id: UUID,
        name: str,
        sample_path: str,
        embedding_path: str,
    ) -> UUID:
        """Insert a new voice row. Returns the generated voice_id."""
        voice_id = uuid4()
        if self.db_dsn is None:
            log.warning("voice_create_db_skipped",
                        voice_id=str(voice_id), reason="db_dsn missing")
            return voice_id

        import psycopg                  # local import — see module docstring
        with psycopg.connect(self.db_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO voices
                        (id, tenant_id, name, sample_path, embedding_path, status)
                    VALUES (%s, %s, %s, %s, %s, 'ready')
                    """,
                    (str(voice_id), str(tenant_id), name,
                     sample_path, embedding_path),
                )
        log.info("voice_inserted", voice_id=str(voice_id), name=name)
        return voice_id

    # ------------------------------------------------------------------
    # Read-only ops
    # ------------------------------------------------------------------

    def list(self, tenant_id: UUID | None = None) -> list[VoiceRecord]:
        if self.db_dsn is None:
            return []
        import psycopg
        sql = (
            "SELECT id::text, tenant_id::text, name, sample_path, "
            "embedding_path, status FROM voices "
        )
        params: tuple = ()
        if tenant_id is not None:
            sql += "WHERE tenant_id = %s "
            params = (str(tenant_id),)
        sql += "ORDER BY created_at DESC"
        with psycopg.connect(self.db_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [
            VoiceRecord(
                voice_id=UUID(r[0]),
                tenant_id=UUID(r[1]),
                name=r[2],
                sample_path=r[3] or "",
                embedding_path=r[4] or "",
                status=r[5],
            )
            for r in rows
        ]
