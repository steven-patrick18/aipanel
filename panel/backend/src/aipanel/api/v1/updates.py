"""Update management — surfaces ``update.sh`` to admins via the GUI.

Two read endpoints + two action endpoints + an SSE stream for live logs.
The actual update logic lives in ``update.sh`` (auto-rollback, DB
backup, dependency-aware restarts) — this module is just a thin
authenticated wrapper so an admin can hit a button instead of SSHing in.

Security:
    - require_admin gates every route
    - the panel runs update.sh via ``sudo -n`` — installer drops a
      sudoers fragment at /etc/sudoers.d/aipanel-update granting just
      that one command
    - every action is audit-logged
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser
from ...auth.permissions import require_admin
from ...db.session import get_session
from ...services.audit_service import log_audit


router = APIRouter(
    prefix="/system/updates",
    tags=["updates"],
    dependencies=[Depends(require_admin)],
)


# Where the installer drops the repo. Override via env in dev/tests.
UPDATE_SCRIPT = os.environ.get("AIPANEL_UPDATE_SCRIPT", "/opt/aipanel/update.sh")
REPO_DIR = os.environ.get("AIPANEL_REPO_DIR",
                          os.path.dirname(UPDATE_SCRIPT))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UpdateInfo(BaseModel):
    current_version:  str
    current_sha:      str
    latest_tag:       str | None = None
    behind_count:     int        = 0
    available_tags:   list[str]  = Field(default_factory=list)
    has_previous:     bool       = False    # rollback target exists
    update_in_progress: bool     = False


class UpdateStartRequest(BaseModel):
    target:      str | None = None    # tag/sha; default = latest
    rollback:    bool       = False
    skip_backup: bool       = False


# ---------------------------------------------------------------------------
# Run tracking — in-memory, single-process. Multiple admins viewing the
# same update share the same stream.
# ---------------------------------------------------------------------------


class _Run:
    def __init__(self) -> None:
        self.id          = str(uuid.uuid4())
        self.started_at  = datetime.now(timezone.utc)
        self.lines: list[str] = []
        self.status      = "running"     # running | ok | failed | error
        self.exit_code: int | None = None
        # Subscribers waiting on new lines.
        self._subscribers: list[asyncio.Queue[str | None]] = []

    def push(self, line: str) -> None:
        self.lines.append(line)
        for q in list(self._subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue[str | None]:
        q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        return q

    def finish(self, status: str, exit_code: int | None) -> None:
        self.status = status
        self.exit_code = exit_code
        for q in list(self._subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass


_runs: dict[str, _Run] = {}
_active_run_id: str | None = None
_run_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Helpers — git invocations against the installed repo
# ---------------------------------------------------------------------------


async def _git(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", REPO_DIR, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {err.decode().strip()[:200]}"
        )
    return out.decode().strip()


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("/info", response_model=UpdateInfo)
async def update_info(user: CurrentUser) -> UpdateInfo:
    """Current installed version + latest available + commits behind."""
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(f"{REPO_DIR} is not a git checkout — set AIPANEL_REPO_DIR "
                    f"or run install.sh from a clone."),
        )
    try:
        current_sha = await _git("rev-parse", "HEAD")
        try:
            current_version = await _git("describe", "--tags", "--always")
        except RuntimeError:
            current_version = current_sha[:12]

        # Update tag list — fail soft, the caller still needs the basics.
        try:
            await _git("fetch", "--tags", "--prune", "--quiet")
        except RuntimeError:
            pass

        try:
            tags_raw = await _git("tag", "--sort=-v:refname")
        except RuntimeError:
            tags_raw = ""
        all_tags = [t for t in tags_raw.splitlines() if t]
        latest_tag = all_tags[0] if all_tags else None

        behind = 0
        if latest_tag:
            try:
                behind = int(await _git(
                    "rev-list", "--count", f"{current_sha}..{latest_tag}"
                ))
            except (RuntimeError, ValueError):
                behind = 0

        prev_file = "/var/lib/aipanel/.previous-version"
        has_prev = os.path.isfile(prev_file) and os.path.getsize(prev_file) > 0

        return UpdateInfo(
            current_version=current_version,
            current_sha=current_sha,
            latest_tag=latest_tag,
            behind_count=behind,
            available_tags=all_tags[:30],
            has_previous=has_prev,
            update_in_progress=_active_run_id is not None,
        )
    except Exception as exc:                                  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"could not query update info: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------


@router.post("/apply", status_code=202)
async def apply_update(
    body: UpdateStartRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> dict:
    """Spawn ``update.sh`` and return a ``run_id`` the UI can stream from."""
    global _active_run_id

    if not shutil.which("sudo"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sudo not available; cannot run update.sh",
        )
    if not os.path.isfile(UPDATE_SCRIPT):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"update script not found at {UPDATE_SCRIPT}",
        )

    async with _run_lock:
        if _active_run_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"another update is in progress: {_active_run_id}",
            )
        run = _Run()
        _runs[run.id] = run
        _active_run_id = run.id

    cmd = ["sudo", "-n", UPDATE_SCRIPT, "--yes"]
    if body.rollback:
        cmd.append("--rollback")
    elif body.target:
        cmd.append(f"--to={body.target}")
    if body.skip_backup:
        cmd.append("--skip-backup")

    asyncio.create_task(_drive_update(run, cmd))

    await log_audit(
        session, user_id=user.id, tenant_id=user.tenant_id,
        action="system.update_start", target_type="system",
        target_id=None,
        payload={"run_id": run.id, "target": body.target,
                 "rollback": body.rollback, "skip_backup": body.skip_backup},
    )
    return {"run_id": run.id}


async def _drive_update(run: _Run, cmd: list[str]) -> None:
    """Run the subprocess, stream stdout/stderr line-by-line into the run."""
    global _active_run_id
    run.push(f"$ {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            run.push(raw.decode("utf-8", errors="replace").rstrip("\n"))
        await proc.wait()
        run.finish("ok" if proc.returncode == 0 else "failed", proc.returncode)
    except Exception as exc:
        run.push(f"[update orchestrator] {exc!r}")
        run.finish("error", -1)
    finally:
        async with _run_lock:
            if _active_run_id == run.id:
                _active_run_id = None


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: CurrentUser) -> dict:
    """Snapshot of a run — for clients that prefer polling over SSE."""
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "id": run.id,
        "status": run.status,
        "exit_code": run.exit_code,
        "started_at": run.started_at.isoformat(),
        "lines": run.lines,
    }


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, user: CurrentUser) -> StreamingResponse:
    """SSE stream of update.sh output. Replays history then tails live lines."""
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    queue = run.subscribe()

    async def gen():
        # Replay history first so a late-joining client sees the whole log.
        for line in run.lines:
            yield f"data: {line}\n\n"
        if run.status != "running":
            yield (f"event: done\n"
                   f"data: {run.status}|{run.exit_code}\n\n")
            return
        while True:
            line = await queue.get()
            if line is None:
                yield (f"event: done\n"
                       f"data: {run.status}|{run.exit_code}\n\n")
                return
            yield f"data: {line}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
