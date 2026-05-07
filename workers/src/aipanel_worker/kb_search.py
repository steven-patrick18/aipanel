"""Knowledge-base search backed by pgvector.

v0.5 is intentionally minimal: when no ``kb_collection_id`` is configured
for the agent, the tool returns "no results" without touching the database.
The full embedding ingest pipeline lands in a later prompt.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger().bind(component="kb_search")


class KBSearch:
    def __init__(self, db_dsn: str, kb_collection_id: str | None) -> None:
        self.db_dsn = db_dsn
        self.kb_collection_id = kb_collection_id

    async def search(self, query: str, limit: int = 5) -> list[str]:
        if not self.kb_collection_id:
            log.debug("kb_disabled", query_preview=query[:80])
            return []

        # Once embeddings + pgvector land, this calls the embed-server, then:
        #   SELECT chunk_text FROM kb_chunks
        #    WHERE kb_collection_id = %s
        #    ORDER BY embedding <-> %s LIMIT %s
        log.info("kb_stub_query",
                 collection=self.kb_collection_id,
                 query_preview=query[:80])
        return []
