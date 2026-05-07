"""Redis pubsub channel naming + publish helper.

Workers publish per-deployment events; the panel SSE endpoint subscribes
to the matching channel and forwards to the browser.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis


def deployment_channel(deployment_id: UUID | str) -> str:
    return f"deployment:{deployment_id}:events"


async def publish_event(
    redis: aioredis.Redis,
    *,
    deployment_id: UUID | str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    payload = {"type": event_type, **data}
    await redis.publish(deployment_channel(deployment_id), json.dumps(payload))
