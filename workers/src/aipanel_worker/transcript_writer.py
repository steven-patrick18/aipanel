"""Stream transcript + tool events to Postgres ``call_events``.

Writes are batched with a 250 ms flush interval so we don't open a connection
per turn. Backpressure: the queue is unbounded — a stuck DB will eat memory
proportional to call duration. We accept that for v0.5 (calls are minutes
long) and revisit if it bites.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import psycopg
import structlog

log = structlog.get_logger().bind(component="transcript_writer")


_INSERT_SQL = (
    "INSERT INTO call_events (call_id, ts, event_type, payload) "
    "VALUES (%s, %s, %s, %s::jsonb)"
)

_FIRST_CALL_INSERT_SQL = (
    "INSERT INTO calls (id, deployment_id, vici_uniqueid, vici_lead_id, "
    "                  phone_number, started_at) "
    "VALUES (%s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (id) DO NOTHING"
)

_END_UPDATE_SQL = (
    "UPDATE calls SET ended_at = %s, duration_sec = %s, "
    "                outcome = %s, dispo_code = %s, "
    "                transcript_path = %s, recording_path = %s "
    "  WHERE id = %s"
)


class TranscriptWriter:
    def __init__(self, db_dsn: str, call_id: str) -> None:
        self.db_dsn = db_dsn
        self.call_id = call_id
        self._queue: asyncio.Queue[tuple[datetime, str, dict] | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(
        self,
        *,
        deployment_id: str,
        vici_uniqueid: str | None,
        vici_lead_id: str | None,
        phone_number: str | None,
    ) -> None:
        """Insert the parent ``calls`` row and start the flusher task."""
        try:
            await asyncio.to_thread(
                self._insert_call_row,
                deployment_id, vici_uniqueid, vici_lead_id, phone_number,
            )
        except psycopg.Error as exc:
            log.warning("calls_insert_failed",
                        call_id=self.call_id, error=str(exc))

        self._task = asyncio.create_task(
            self._flush_loop(), name=f"transcript-flush-{self.call_id}"
        )

    async def stop(
        self,
        *,
        outcome: str,
        dispo_code: str,
        transcript_path: str = "",
        recording_path: str = "",
        duration_sec: int = 0,
    ) -> None:
        """Drain the queue and update the parent ``calls`` row."""
        await self._queue.put(None)
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:                     # pragma: no cover
                self._task.cancel()
        try:
            await asyncio.to_thread(
                self._update_call_row,
                outcome, dispo_code, transcript_path,
                recording_path, duration_sec,
            )
        except psycopg.Error as exc:
            log.warning("calls_update_failed",
                        call_id=self.call_id, error=str(exc))

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def write(self, event_type: str, payload: dict[str, Any]) -> None:
        """Non-blocking write. Safe to call from sync contexts."""
        try:
            self._queue.put_nowait((datetime.now(timezone.utc), event_type, payload))
        except asyncio.QueueFull:                            # pragma: no cover
            log.warning("transcript_queue_full",
                        call_id=self.call_id, dropped_event=event_type)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _insert_call_row(
        self,
        deployment_id: str,
        vici_uniqueid: str | None,
        vici_lead_id: str | None,
        phone_number: str | None,
    ) -> None:
        # vici_uniqueid is UNIQUE in the calls table; collisions can happen
        # if SIP retries — ON CONFLICT DO NOTHING swallows the duplicate.
        with psycopg.connect(self.db_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _FIRST_CALL_INSERT_SQL,
                    (
                        self.call_id, deployment_id,
                        vici_uniqueid or self.call_id,   # NOT NULL on the column
                        vici_lead_id, phone_number,
                        datetime.now(timezone.utc),
                    ),
                )

    def _update_call_row(
        self,
        outcome: str,
        dispo_code: str,
        transcript_path: str,
        recording_path: str,
        duration_sec: int,
    ) -> None:
        with psycopg.connect(self.db_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _END_UPDATE_SQL,
                    (
                        datetime.now(timezone.utc), duration_sec,
                        outcome, dispo_code,
                        transcript_path, recording_path,
                        self.call_id,
                    ),
                )

    async def _flush_loop(self) -> None:
        batch: list[tuple[datetime, str, dict]] = []
        while True:
            timeout = 0.25 if batch else None
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                await self._flush(batch)
                batch = []
                continue
            if item is None:
                await self._flush(batch)
                return
            batch.append(item)
            if len(batch) >= 50:
                await self._flush(batch)
                batch = []

    async def _flush(self, batch: list[tuple[datetime, str, dict]]) -> None:
        if not batch:
            return
        try:
            await asyncio.to_thread(self._sync_flush, batch)
        except psycopg.Error as exc:
            log.warning("transcript_flush_failed",
                        call_id=self.call_id, error=str(exc),
                        dropped=len(batch))

    def _sync_flush(self, batch: list[tuple[datetime, str, dict]]) -> None:
        rows = [
            (self.call_id, ts, etype, json.dumps(payload, default=str))
            for ts, etype, payload in batch
        ]
        with psycopg.connect(self.db_dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(_INSERT_SQL, rows)
