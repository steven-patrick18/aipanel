"""Loop B: heartbeat every active session every 1.5 s, capped concurrency.

Every supervised SessionWorker has its own heartbeat coroutine. Concurrent
HTTP fan-out across all of them is bounded by a global semaphore so we don't
DDoS the ViciDial Apache pool.
"""

from __future__ import annotations

import asyncio

import structlog

from .session_supervisor import SessionSupervisor
from .session_worker import SessionWorker

log = structlog.get_logger().bind(component="heartbeat")


class HeartbeatScheduler:
    def __init__(
        self,
        supervisor: SessionSupervisor,
        *,
        interval_sec: float = 1.5,
        max_concurrency: int = 200,
    ) -> None:
        self.supervisor = supervisor
        self.interval_sec = interval_sec
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self._stop = asyncio.Event()
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        log.info("heartbeat_scheduler_start",
                 interval_sec=self.interval_sec,
                 max_concurrency=self.semaphore._value)
        while not self._stop.is_set():
            self._reconcile_tasks()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks.values():
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def _reconcile_tasks(self) -> None:
        live_ids = set(self.supervisor.workers.keys())

        # Spawn for new workers.
        for did in live_ids - self._tasks.keys():
            worker = self.supervisor.workers[did]
            self._tasks[did] = asyncio.create_task(
                self._beat_loop(worker),
                name=f"vici-hb-{did}",
            )

        # Stop tasks for departed workers.
        for did in self._tasks.keys() - live_ids:
            t = self._tasks.pop(did)
            t.cancel()

    async def _beat_loop(self, worker: SessionWorker) -> None:
        try:
            while not self._stop.is_set():
                async with self.semaphore:
                    try:
                        await worker.heartbeat()
                    except Exception as exc:                 # pragma: no cover
                        log.exception("heartbeat_call_failed",
                                      deployment_id=worker.state.deployment_id,
                                      error=str(exc))
                await asyncio.sleep(self.interval_sec)
        except asyncio.CancelledError:
            return
