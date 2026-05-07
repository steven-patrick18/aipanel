"""ARQ job: nightly DB + MinIO backup.

Skeleton for v0.7. Full implementation needs:

* ``pg_dump`` of the aipanel database to ``/var/lib/aipanel/backups/``
* ``mc mirror`` (MinIO client) of the recordings + transcripts buckets
* Optional retention policy (keep 30 daily / 12 monthly)

For now we shell out to a script if it exists, otherwise log + no-op.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone

import structlog

log = structlog.get_logger().bind(component="backup_job")

BACKUP_SCRIPT = "/opt/aipanel/scripts/backup.sh"


async def nightly_backup(ctx: dict) -> dict:
    if not os.path.isfile(BACKUP_SCRIPT) or not os.access(BACKUP_SCRIPT, os.X_OK):
        log.info("backup_script_missing", path=BACKUP_SCRIPT)
        return {"ok": False, "reason": "backup script not installed yet"}

    started = datetime.now(timezone.utc)
    proc = await asyncio.create_subprocess_exec(
        BACKUP_SCRIPT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    duration_sec = (datetime.now(timezone.utc) - started).total_seconds()
    if proc.returncode == 0:
        log.info("backup_ok", duration_sec=duration_sec,
                 output=stdout.decode("utf-8", "replace")[-1000:])
        return {"ok": True, "duration_sec": duration_sec}
    log.error("backup_failed", returncode=proc.returncode,
              stderr=stderr.decode("utf-8", "replace")[-2000:])
    return {"ok": False, "returncode": proc.returncode}
