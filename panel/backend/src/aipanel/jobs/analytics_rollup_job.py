"""ARQ cron job: hourly analytics rollup.

v0.7 is a stub. Once analytics traffic gets large enough that live SQL
aggregations on ``calls`` slow down the dashboard, this job should
``REFRESH MATERIALIZED VIEW CONCURRENTLY`` over a small set of pre-built
rollups (per-tenant per-day call counts, dispo breakdown, etc.).
"""

from __future__ import annotations

import structlog

log = structlog.get_logger().bind(component="analytics_rollup_job")


async def analytics_rollup(ctx: dict) -> dict:
    log.info("analytics_rollup_stub_run",
             todo="implement materialized view refreshes")
    return {"ok": True, "stub": True}
