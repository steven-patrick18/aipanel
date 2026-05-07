"""Per-call lifecycle: parse INVITE, set up bridge, request worker, answer.

Flow on incoming INVITE
-----------------------

1. Endpoint's account-level ``onIncomingCall`` invokes
   ``CallRouter.handle_invite(account, prm)``.
2. We check the global "shutting down" flag; if set, respond with 503 and
   return — no bridge or worker request.
3. Parse vici headers from ``prm.rdata.wholeMsg``.
4. Build a ``CallContext`` and ``AudioBridge``; create the unix socket.
5. Publish a worker request to the Redis stream; wait up to
   ``worker_connect_timeout_sec`` for the worker to connect.
6. On success: answer 200 OK, send the CallContext to the worker as a
   ``CONTROL`` frame, attach PJSIP audio media when ``CONFIRMED``.
7. On any failure: respond with 503 and tear down.

PJSIP threading: ``handle_invite`` runs on a PJSIP callback thread. We do
the synchronous worker-wait inline; for a typical 5 s timeout that's
acceptable since each call is its own pj.Call thread context. If this
becomes a hotspot we can offload to a small thread pool.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable
from uuid import UUID, uuid4

import structlog

try:
    import pjsua2 as pj
except ImportError:                                          # pragma: no cover
    pj = None  # type: ignore[assignment]

from .audio_bridge import AudioBridge
from .config import SipConfig
from .header_parser import parse_headers
from .models import CallContext
from .worker_dispatcher import WorkerDispatcher

if TYPE_CHECKING:                                            # pragma: no cover
    from .endpoint import SipEndpoint

log = structlog.get_logger().bind(component="call_handler")


# ---------------------------------------------------------------------------
# Per-call pj.Call subclass
# ---------------------------------------------------------------------------

if pj is not None:

    class _IncomingCall(pj.Call):                            # type: ignore[misc]
        """Wraps a pj.Call to plumb media + hangup events into the bridge."""

        def __init__(
            self,
            account,
            call_id: UUID,
            bridge: AudioBridge,
            on_disconnected: Callable[[UUID], None],
            call_id_arg: int = pj.PJSUA_INVALID_ID,
        ) -> None:
            super().__init__(account, call_id_arg)
            self._call_id = call_id
            self._bridge = bridge
            self._on_disconnected = on_disconnected
            self._media_attached = False

        # --- PJSIP callbacks ---

        def onCallState(self, prm) -> None:                  # noqa: N802
            try:
                info = self.getInfo()
            except pj.Error:
                return
            log.info("call_state",
                     call_id=str(self._call_id),
                     state=info.stateText,
                     last_status=info.lastStatusCode)
            if info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                try:
                    self._bridge.send_hangup()
                except Exception:                            # pragma: no cover
                    pass
                self._bridge.close()
                self._on_disconnected(self._call_id)

        def onCallMediaState(self, prm) -> None:             # noqa: N802
            try:
                info = self.getInfo()
            except pj.Error:                                 # pragma: no cover
                return
            for i, mi in enumerate(info.media):
                if (
                    mi.type == pj.PJMEDIA_TYPE_AUDIO
                    and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE
                    and not self._media_attached
                ):
                    try:
                        am = pj.AudioMedia.typecastFromMedia(self.getMedia(i))
                        self._bridge.attach_media(am)
                        self._media_attached = True
                    except pj.Error as exc:
                        log.error("media_attach_failed",
                                  call_id=str(self._call_id), error=str(exc))
                        self._safe_hangup(503)
                    break

        def onDtmfDigit(self, prm) -> None:                  # noqa: N802
            digit = getattr(prm, "digit", "")
            log.info("dtmf_received",
                     call_id=str(self._call_id), digit=digit)
            self._bridge.send_dtmf(digit)

        # --- helpers ---

        def _safe_hangup(self, code: int) -> None:
            try:
                cprm = pj.CallOpParam()
                cprm.statusCode = code
                self.hangup(cprm)
            except pj.Error:                                 # pragma: no cover
                pass


# ---------------------------------------------------------------------------
# CallRouter
# ---------------------------------------------------------------------------

class CallState:
    """Process-wide state for in-flight calls + shutdown flag."""

    def __init__(self) -> None:
        self._calls: dict[UUID, "object"] = {}
        self._lock = threading.Lock()
        self.shutting_down = False

    def add(self, call_id: UUID, call) -> None:
        with self._lock:
            self._calls[call_id] = call

    def pop(self, call_id: UUID):
        with self._lock:
            return self._calls.pop(call_id, None)

    def active_count(self) -> int:
        with self._lock:
            return len(self._calls)

    def snapshot(self) -> list:
        with self._lock:
            return list(self._calls.values())


class CallRouter:
    """Owner of every incoming call decision."""

    def __init__(
        self,
        endpoint: "SipEndpoint",
        cfg: SipConfig,
        state: CallState,
        dispatcher: WorkerDispatcher,
        on_call_ended: Callable[[str], None] | None = None,
        on_frame_dropped: Callable[[], None] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.cfg = cfg
        self.state = state
        self.dispatcher = dispatcher
        self._on_call_ended = on_call_ended or (lambda outcome: None)
        self._on_frame_dropped = on_frame_dropped or (lambda: None)

    def handle_invite(self, pj_account, prm) -> None:
        """Account-level ``onIncomingCall`` shim."""
        if pj is None:                                       # pragma: no cover
            return
        if self.state.shutting_down:
            self._reject(pj_account, prm, 503, "shutting down")
            return

        call_id = uuid4()
        log.info("invite_received", call_id=str(call_id))

        # Header parsing — best effort. If rdata is missing we just continue
        # with no vici metadata.
        raw_msg = ""
        try:
            raw_msg = getattr(prm.rdata, "wholeMsg", "") or ""
        except Exception:                                    # pragma: no cover
            pass
        headers = parse_headers(raw_msg)

        socket_path = f"{self.cfg.runtime_dir}/{call_id}.sock"
        ctx = CallContext(
            call_id=call_id,
            deployment_id=pj_account.model.deployment_id,
            account_login=pj_account.model.phone_login,
            socket_path=socket_path,
            vici_lead_id=headers.get("vici_lead_id"),
            vici_uniqueid=headers.get("vici_uniqueid"),
            vici_campaign=headers.get("vici_campaign"),
            vici_phone=headers.get("vici_phone"),
            p_asserted_identity=headers.get("p_asserted_identity"),
        )

        bridge = AudioBridge(
            call_id=call_id,
            socket_path=socket_path,
            on_dropped_frame=self._on_frame_dropped,
            on_worker_hangup=lambda cid=call_id: self._worker_initiated_hangup(cid),
        )

        try:
            bridge.setup_socket()
        except OSError as exc:
            log.error("socket_setup_failed",
                      call_id=str(call_id), path=socket_path, error=str(exc))
            self._reject(pj_account, prm, 500, "internal error")
            return

        if self.dispatcher.publish_request(ctx) is None:
            bridge.close()
            self._reject(pj_account, prm, 503, "dispatch failed")
            return

        # Wait for worker to connect. This blocks the PJSIP thread for up to
        # worker_connect_timeout_sec — acceptable since rejection is the only
        # alternative and 5 s is well within INVITE retransmission window.
        try:
            bridge.accept_worker(self.cfg.worker_connect_timeout_sec)
        except TimeoutError as exc:
            log.warning("worker_accept_timeout",
                        call_id=str(call_id), error=str(exc))
            bridge.close()
            self._reject(pj_account, prm, 503, "no worker available")
            return
        except OSError as exc:
            log.error("worker_accept_failed",
                      call_id=str(call_id), error=str(exc))
            bridge.close()
            self._reject(pj_account, prm, 500, "internal error")
            return

        # Build the pj.Call wrapper and answer 200 OK.
        try:
            call = _IncomingCall(
                pj_account, call_id, bridge,
                on_disconnected=self._on_disconnected,
                call_id_arg=prm.callId,
            )
        except pj.Error as exc:
            log.error("call_create_failed",
                      call_id=str(call_id), error=str(exc))
            bridge.close()
            self._reject(pj_account, prm, 500, "internal error")
            return

        # Send the CallContext to the worker as the very first frame.
        bridge.send_control({"type": "call_context", **ctx.model_dump(mode="json")})

        cprm = pj.CallOpParam()
        cprm.statusCode = 200
        try:
            call.answer(cprm)
        except pj.Error as exc:
            log.error("call_answer_failed",
                      call_id=str(call_id), error=str(exc))
            bridge.close()
            return

        self.state.add(call_id, call)
        log.info("call_answered", call_id=str(call_id),
                 deployment_id=str(ctx.deployment_id),
                 vici_uniqueid=ctx.vici_uniqueid)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _reject(self, pj_account, prm, code: int, reason: str) -> None:
        """Answer the INVITE with a non-2xx status, no media."""
        if pj is None:                                       # pragma: no cover
            return
        try:
            tmp = pj.Call(pj_account, prm.callId)
            cprm = pj.CallOpParam()
            cprm.statusCode = code
            cprm.reason = reason
            tmp.answer(cprm)
        except pj.Error as exc:                              # pragma: no cover
            log.warning("reject_failed", code=code, error=str(exc))

    def _on_disconnected(self, call_id: UUID) -> None:
        call = self.state.pop(call_id)
        if call is None:
            return
        self._on_call_ended("completed")

    def _worker_initiated_hangup(self, call_id: UUID) -> None:
        call = self.state.pop(call_id)
        if call is None:
            return
        try:
            self.endpoint.register_thread(f"sip-bye-{call_id}")
            cprm = pj.CallOpParam()
            cprm.statusCode = 200
            call.hangup(cprm)
        except Exception as exc:                             # pragma: no cover
            log.warning("worker_hangup_send_failed",
                        call_id=str(call_id), error=str(exc))
        self._on_call_ended("worker_hangup")

    def hangup_all(self) -> None:
        """Send BYE to every active call. Used during graceful shutdown."""
        if pj is None:                                       # pragma: no cover
            return
        for call in self.state.snapshot():
            try:
                self.endpoint.register_thread("sip-shutdown-bye")
                cprm = pj.CallOpParam()
                cprm.statusCode = 200
                call.hangup(cprm)
            except Exception as exc:                         # pragma: no cover
                log.warning("force_hangup_failed", error=str(exc))
