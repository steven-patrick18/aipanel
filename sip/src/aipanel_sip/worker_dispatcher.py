"""Worker dispatch — publish a request to Redis Streams and let a worker pick it up.

The SIP layer never spawns workers. It:

1. Creates the per-call unix socket via ``AudioBridge.setup_socket()``.
2. ``WorkerDispatcher.publish_request()`` XADDs a message to
   ``aipanel:worker_requests`` containing the call context + socket path.
3. Workers (separate processes, built in a later prompt) consume the stream
   with a consumer group, choose whether they have capacity, and connect to
   the socket.
4. SIP calls ``AudioBridge.accept_worker(timeout)`` to wait for that connect.

If no worker connects in time the call is rejected with 503 — see
``call_handler.IncomingCall.handle_invite``.
"""

from __future__ import annotations

from typing import Any

import redis
import structlog

from .models import CallContext

log = structlog.get_logger().bind(component="worker_dispatcher")


class WorkerDispatcher:
    """Thin wrapper around the Redis stream that workers consume."""

    def __init__(self, redis_client: redis.Redis, stream_key: str) -> None:
        self._r = redis_client
        self._stream_key = stream_key

    def publish_request(self, ctx: CallContext) -> str | None:
        """Publish a worker request. Returns the stream entry ID, or None on failure.

        Failure modes:
        - Redis unreachable (network, auth) → log + return None; caller hangs up.
        - Redis returns oversized response → unlikely; logged and treated as failure.
        """
        payload: dict[str, Any] = {
            "call_id":             str(ctx.call_id),
            "deployment_id":       str(ctx.deployment_id),
            "account_login":       ctx.account_login,
            "socket_path":         ctx.socket_path,
            "vici_lead_id":        ctx.vici_lead_id or "",
            "vici_uniqueid":       ctx.vici_uniqueid or "",
            "vici_campaign":       ctx.vici_campaign or "",
            "vici_phone":          ctx.vici_phone or "",
            "p_asserted_identity": ctx.p_asserted_identity or "",
            "started_at":          ctx.started_at.isoformat(),
        }
        try:
            entry_id = self._r.xadd(self._stream_key, payload, maxlen=10_000, approximate=True)
        except redis.RedisError as exc:
            log.error("worker_request_publish_failed",
                      call_id=str(ctx.call_id), error=str(exc))
            return None

        # redis-py returns bytes when decode_responses=False; normalise to str.
        if isinstance(entry_id, bytes):
            entry_id = entry_id.decode("ascii", "replace")
        log.info("worker_request_published",
                 call_id=str(ctx.call_id), stream_id=entry_id)
        return entry_id
