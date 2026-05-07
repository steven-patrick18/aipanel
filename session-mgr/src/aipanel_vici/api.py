"""FastAPI surface for workers + the panel.

Two URL families coexist:

* **Canonical** (this prompt's spec): ``/api/v1/deployments/{id}/...``
* **Worker compat shim** (prompt 6's ViciClient): ``/api/vici/...``
  Resolves the worker's ``call_id`` → ``deployment_id`` via Postgres.

Auth: every request must carry ``X-AIPanel-Token: <SESSION_MGR_TOKEN>``.
The token comes from /etc/aipanel/secrets.env.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import psycopg
import structlog
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from .adapters.base import AdapterError, SessionExpired
from .config import SessionMgrConfig
from .metrics import M_ACTION_LATENCY, M_API_REQUESTS
from .session_supervisor import SessionSupervisor

log = structlog.get_logger().bind(component="api")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DisposeBody(BaseModel):
    status: str = Field(..., min_length=1, max_length=64)
    callback_datetime: str | None = None
    notes: str = ""


class TransferBody(BaseModel):
    ingroup_id: str = Field(..., min_length=1)
    summary: str = ""


class PauseBody(BaseModel):
    pause_code: str = Field(..., min_length=1, max_length=64)


class ManualDialBody(BaseModel):
    phone_number: str = Field(..., min_length=4, max_length=32)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def make_app(cfg: SessionMgrConfig, supervisor: SessionSupervisor) -> FastAPI:
    app = FastAPI(title="aipanel-session-mgr", version="1.0.0")
    app.state.cfg = cfg
    app.state.supervisor = supervisor

    # Shared auth dep.
    async def _check_auth(request: Request) -> None:
        token = request.headers.get("X-AIPanel-Token", "")
        if token != cfg.auth_token:
            M_API_REQUESTS.labels(route=request.url.path, status="401").inc()
            raise HTTPException(status_code=401, detail="bad token")

    # ------------------------------------------------------------------
    # Health + metrics (no auth so prometheus + nginx can probe)
    # ------------------------------------------------------------------
    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "sessions": len(supervisor.workers),
            "adapter": cfg.adapter,
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(),
                        media_type=CONTENT_TYPE_LATEST)

    # ------------------------------------------------------------------
    # Canonical /api/v1/deployments/{id}/...
    # ------------------------------------------------------------------

    canon = APIRouter(prefix="/api/v1/deployments",
                      dependencies=[Depends(_check_auth)])

    def _worker_or_404(deployment_id: str):
        w = supervisor.get_worker(deployment_id)
        if w is None:
            raise HTTPException(status_code=404, detail="deployment not managed")
        return w

    @canon.get("/{deployment_id}/status")
    async def get_status(deployment_id: str = Path(...)) -> dict:
        w = _worker_or_404(deployment_id)
        s = w.state
        return {
            "deployment_id": s.deployment_id,
            "status": s.status.value,
            "vici_user": s.vici_user,
            "phone_login": s.phone_login,
            "campaign": s.campaign,
            "last_heartbeat_at": s.last_heartbeat_at,
            "heartbeat_failures": s.heartbeat_failures,
            "login_attempts": s.login_attempts,
            "last_error": s.last_error,
        }

    @canon.get("/{deployment_id}/call_info")
    async def call_info(deployment_id: str = Path(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("call_info"):
            try:
                info = await w.get_call_info()
            except SessionExpired as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except AdapterError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "lead_id": info.lead_id,
            "uniqueid": info.uniqueid,
            "phone_number": info.phone_number,
            "campaign_id": info.campaign_id,
            "list_id": info.list_id,
        }

    @canon.get("/{deployment_id}/lead/{lead_id}")
    async def lead(deployment_id: str = Path(...), lead_id: str = Path(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("lead"):
            try:
                lead = await w.get_lead(lead_id)
            except AdapterError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "lead_id": lead.lead_id,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "phone_number": lead.phone_number,
            "email": lead.email,
            "address": lead.address,
            "city": lead.city,
            "state": lead.state,
            "postal_code": lead.postal_code,
        }

    @canon.post("/{deployment_id}/dispose")
    async def dispose(deployment_id: str = Path(...),
                      body: DisposeBody = Body(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("dispose"):
            try:
                await w.dispose(body.status, body.callback_datetime, body.notes)
            except SessionExpired as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True}

    @canon.post("/{deployment_id}/transfer")
    async def transfer(deployment_id: str = Path(...),
                       body: TransferBody = Body(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("transfer"):
            try:
                await w.transfer_conference(body.ingroup_id, body.summary)
            except SessionExpired as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True}

    @canon.post("/{deployment_id}/pause")
    async def pause(deployment_id: str = Path(...),
                    body: PauseBody = Body(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("pause"):
            try:
                await w.pause(body.pause_code)
            except SessionExpired as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True}

    @canon.post("/{deployment_id}/resume")
    async def resume(deployment_id: str = Path(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("resume"):
            try:
                await w.resume()
            except SessionExpired as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True}

    @canon.post("/{deployment_id}/hangup")
    async def hangup(deployment_id: str = Path(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("hangup"):
            try:
                await w.hangup()
            except SessionExpired as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True}

    @canon.post("/{deployment_id}/manual-dial")
    async def manual_dial(deployment_id: str = Path(...),
                          body: ManualDialBody = Body(...)) -> dict:
        w = _worker_or_404(deployment_id)
        with _timed("manual_dial"):
            try:
                await w.manual_dial(body.phone_number)
            except SessionExpired as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except AdapterError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": True, "phone_number": body.phone_number}

    @canon.post("/{deployment_id}/start")
    async def start(deployment_id: str = Path(...)) -> dict:
        # Force the supervisor to pick this deployment up on the next tick.
        # For instant action, look up the worker and trigger start() if absent.
        w = supervisor.get_worker(deployment_id)
        if w is None:
            return {"ok": True, "queued": True}
        return {"ok": True, "already_running": True}

    @canon.post("/{deployment_id}/stop")
    async def stop_dep(deployment_id: str = Path(...)) -> dict:
        w = _worker_or_404(deployment_id)
        await w.stop()
        return {"ok": True}

    app.include_router(canon)

    # ------------------------------------------------------------------
    # Worker compat shim — /api/vici/* matching the worker's ViciClient
    # ------------------------------------------------------------------

    compat = APIRouter(prefix="/api/vici",
                       dependencies=[Depends(_check_auth)])

    async def _worker_for_call(call_id: str | None) -> "SessionWorker":  # type: ignore[name-defined]
        if not call_id:
            raise HTTPException(status_code=400, detail="call_id required")
        deployment_id = await _resolve_call_to_deployment(cfg.db_dsn, call_id)
        if deployment_id is None:
            raise HTTPException(status_code=404,
                                detail=f"call_id {call_id} not found in calls table")
        return _worker_or_404(deployment_id)

    @compat.get("/lead/{lead_id}")
    async def compat_lead(lead_id: str, request: Request) -> dict:
        # The worker's get_lead() doesn't pass a deployment_id. We honour
        # an optional ?deployment_id=... or take the first available worker.
        deployment_id = request.query_params.get("deployment_id")
        if deployment_id:
            w = _worker_or_404(deployment_id)
        elif supervisor.workers:
            w = next(iter(supervisor.workers.values()))
        else:
            raise HTTPException(status_code=503, detail="no managed deployments")
        with _timed("compat_lead"):
            lead = await w.get_lead(lead_id)
        return {
            "lead_id": lead.lead_id,
            "name": (lead.first_name + " " + lead.last_name).strip()
                    or "the customer",
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "phone_number": lead.phone_number,
            "email": lead.email,
        }

    @compat.post("/disposition")
    async def compat_dispo(body: dict = Body(...)) -> dict:
        w = await _worker_for_call(body.get("call_id"))
        with _timed("compat_dispo"):
            await w.dispose(
                status=body.get("dispo_code", "DONE"),
                notes=body.get("notes", ""),
            )
        return {"ok": True}

    @compat.post("/transfer")
    async def compat_transfer(body: dict = Body(...)) -> dict:
        w = await _worker_for_call(body.get("call_id"))
        with _timed("compat_transfer"):
            await w.transfer_conference(
                ingroup_id=body.get("ingroup_id", ""),
                summary=body.get("summary", ""),
            )
        return {"ok": True}

    @compat.post("/dnc")
    async def compat_dnc(body: dict = Body(...)) -> dict:
        # Map to a dispose with a DNC status — most ViciDial installs treat
        # DNC as a disposition that triggers a dialler-side DNC list update.
        # For the canonical path the panel should call /api/v1/.../dispose
        # with status="DNC" directly.
        deployment_id = body.get("deployment_id")
        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")
        w = _worker_or_404(deployment_id)
        await w.dispose(status="DNC", notes=body.get("reason", ""))
        return {"ok": True}

    @compat.post("/callback")
    async def compat_cb(body: dict = Body(...)) -> dict:
        deployment_id = body.get("deployment_id")
        if not deployment_id:
            raise HTTPException(status_code=400, detail="deployment_id required")
        w = _worker_or_404(deployment_id)
        await w.dispose(
            status="CALLBK",
            callback_datetime=body.get("when"),
            notes=body.get("notes", ""),
        )
        return {"ok": True}

    app.include_router(compat)
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _timed:
    """Context manager that observes M_ACTION_LATENCY[label]."""
    def __init__(self, label: str) -> None:
        self.label = label
        self._t0 = 0.0

    def __enter__(self) -> "_timed":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc) -> None:
        M_ACTION_LATENCY.labels(action=self.label).observe(
            time.monotonic() - self._t0
        )


async def _resolve_call_to_deployment(db_dsn: str, call_id: str) -> str | None:
    """Look up calls.deployment_id by call_id. Sync via to_thread."""
    import asyncio

    def _sync() -> str | None:
        try:
            with psycopg.connect(db_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT deployment_id::text FROM calls WHERE id = %s",
                        (call_id,),
                    )
                    row = cur.fetchone()
        except psycopg.Error as exc:
            log.warning("call_to_deployment_lookup_failed", error=str(exc))
            return None
        return row[0] if row else None

    return await asyncio.to_thread(_sync)
