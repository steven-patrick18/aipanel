"""Redis-backed JWT denylist for /logout.

We can't truly invalidate a JWT (they're stateless by design) so we keep
a small per-jti record with TTL = remaining-token-lifetime. ``is_denied``
fires once per request from the auth dep — Redis SET membership is O(1)
and the round trip is sub-millisecond on a local Redis.
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis
import structlog

from ..config import get_config

log = structlog.get_logger().bind(component="jwt_denylist")

_DENYLIST_PREFIX = "auth:denylist:"
_pool: aioredis.Redis | None = None


async def _get() -> aioredis.Redis | None:
    global _pool
    if _pool is None:
        try:
            _pool = aioredis.from_url(
                get_config().redis.url, decode_responses=True,
            )
        except Exception as exc:                             # pragma: no cover
            log.warning("denylist_redis_unavailable", error=str(exc))
            return None
    return _pool


async def deny(jti: str, expires_at_unix: int) -> None:
    """Add ``jti`` to the denylist with TTL = remaining token lifetime."""
    if not jti:
        return
    r = await _get()
    if r is None:
        return
    ttl = max(1, expires_at_unix - int(time.time()))
    try:
        await r.setex(_DENYLIST_PREFIX + jti, ttl, "1")
    except Exception as exc:                                 # pragma: no cover
        log.warning("denylist_set_failed", jti=jti[:6], error=str(exc))


async def is_denied(jti: str) -> bool:
    """True if the jti is on the denylist; False on Redis failure (fail-open
    so a Redis hiccup doesn't lock everyone out)."""
    if not jti:
        return False
    r = await _get()
    if r is None:
        return False
    try:
        return bool(await r.exists(_DENYLIST_PREFIX + jti))
    except Exception:                                        # pragma: no cover
        return False


async def aclose() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
