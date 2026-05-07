"""ARQ job: mine successful calls into a campaign's few-shot pool.

For each campaign (or one specific campaign when called from the API):

1. Find calls in the last N days where ``dispo_code`` is in
   ``campaign.success_dispos`` AND the call belongs to this campaign
   (either via ``calls.campaign_id`` or via the deployment's
   ``aipanel_campaign_id``).
2. For each successful call, pull paired user/agent turns from
   ``call_events`` (event_type ``user_speech`` immediately followed by
   ``agent_speech``).
3. Score each pair: short user + thoughtful agent reply scores higher.
4. Keep the top K pairs across the window, write them to
   ``campaign.few_shot_pool``.

The worker (call_session.py + prompt_builder.py) reads
``few_shot_pool`` at call setup and injects the top examples into the
LLM system prompt as "EXAMPLES OF SUCCESSFUL EXCHANGES".

Cron: hourly via ``WorkerSettings.cron_jobs`` in arq_worker.py.
On-demand: invoked by ``POST /api/v1/campaigns/{id}/refresh-few-shot``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, update

from ..db.models.calls import Call, CallEvent
from ..db.models.campaigns import Campaign
from ..db.models.vici import Deployment
from ..db.session import get_sessionmaker

log = structlog.get_logger().bind(component="campaign_mine_job")

# Tunables.
DEFAULT_WINDOW_DAYS = 30
KEEP_TOP_K          = 12
MAX_CALLS_PER_RUN   = 200    # cap memory + DB load


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_pair(user_text: str, agent_text: str) -> float:
    """Heuristic 0–1. Favours concise user prompts answered with substance.

    The full version would use an LLM judge; this is the cheap proxy that
    surfaces good exchanges without GPU calls. Tuned on the assumption that
    the top exchange in a successful call is the *qualifying* moment, where
    the user reveals intent and the agent capitalises in 1-3 sentences.
    """
    u = (user_text or "").strip()
    a = (agent_text or "").strip()
    if not u or not a:
        return 0.0

    u_words = len(u.split())
    a_words = len(a.split())

    # Want user 4-25 words (real intent, not "uh huh"), agent 8-50 (substance,
    # not a one-word brush-off, not a wall of text).
    user_band  = 1.0 if 4  <= u_words <= 25 else 0.45
    agent_band = 1.0 if 8  <= a_words <= 50 else 0.50

    # Bonus for question/answer shape.
    qa_bonus = 0.10 if "?" in u else 0.0
    # Bonus for confirming/acknowledging.
    ack_bonus = 0.05 if any(t in a.lower() for t in
                            ("sure", "absolutely", "got it", "of course")) else 0.0

    return min(1.0, 0.5 * user_band + 0.4 * agent_band + qa_bonus + ack_bonus)


# ---------------------------------------------------------------------------
# Per-campaign mine
# ---------------------------------------------------------------------------

async def _mine_one_campaign(
    session,
    campaign: Campaign,
    window_days: int,
) -> list[dict[str, Any]]:
    success_dispos = list(campaign.success_dispos or [])
    if not success_dispos:
        log.info("campaign_no_success_dispos",
                 campaign_id=str(campaign.id), name=campaign.name)
        return []

    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Pull successful calls for this campaign in window.
    rows = (await session.execute(
        select(Call.id, Call.dispo_code)
        .join(Deployment, Deployment.id == Call.deployment_id)
        .where(Deployment.tenant_id == campaign.tenant_id)
        .where(Call.started_at >= since)
        .where(Call.dispo_code.in_(success_dispos))
        .where(
            (Call.campaign_id == campaign.id)
            | (Deployment.aipanel_campaign_id == campaign.id)
        )
        .order_by(Call.started_at.desc())
        .limit(MAX_CALLS_PER_RUN)
    )).all()

    log.info("campaign_mine_start",
             campaign_id=str(campaign.id), name=campaign.name,
             window_days=window_days, candidate_calls=len(rows))

    candidates: list[tuple[float, dict[str, Any]]] = []
    now = datetime.now(timezone.utc)

    for call_id, _dispo in rows:
        events = (await session.execute(
            select(CallEvent.ts, CallEvent.event_type, CallEvent.payload)
            .where(CallEvent.call_id == call_id)
            .where(CallEvent.event_type.in_(("user_speech", "agent_speech")))
            .order_by(CallEvent.ts.asc())
        )).all()

        # Walk pairs: user_speech immediately followed by agent_speech.
        for i in range(len(events) - 1):
            ts_u, et_u, pl_u = events[i]
            ts_a, et_a, pl_a = events[i + 1]
            if et_u != "user_speech" or et_a != "agent_speech":
                continue
            user_text  = str((pl_u or {}).get("text", "")).strip()
            agent_text = str((pl_a or {}).get("text", "")).strip()
            score = _score_pair(user_text, agent_text)
            if score < 0.5:
                continue
            candidates.append((score, {
                "user":     user_text,
                "agent":    agent_text,
                "score":    round(score, 3),
                "call_id":  str(call_id),
                "mined_at": now.isoformat(),
            }))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = [c[1] for c in candidates[:KEEP_TOP_K]]
    log.info("campaign_mine_done",
             campaign_id=str(campaign.id),
             pairs_considered=len(candidates),
             pairs_kept=len(top))
    return top


# ---------------------------------------------------------------------------
# Public ARQ entrypoints
# ---------------------------------------------------------------------------

async def campaign_mine_few_shot(
    ctx: dict,
    campaign_id: str | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    """Mine one campaign (when ``campaign_id`` given) or every active campaign."""
    sm = get_sessionmaker()
    written = 0
    async with sm() as session:
        if campaign_id is not None:
            target = await session.get(Campaign, UUID(campaign_id))
            campaigns = [target] if target is not None else []
        else:
            campaigns = list((await session.execute(
                select(Campaign).where(Campaign.status == "active")
            )).scalars().all())

        for c in campaigns:
            if c is None:
                continue
            top = await _mine_one_campaign(session, c, window_days)
            await session.execute(
                update(Campaign)
                .where(Campaign.id == c.id)
                .values(few_shot_pool=top,
                        few_shot_updated_at=datetime.now(timezone.utc))
            )
            written += 1
        await session.commit()
    return {"ok": True, "campaigns_processed": written}
