"""Cluster endpoints — node lifecycle: list, join-token, drain, remove.

Workflow for adding a node:
    1. Admin POSTs to /cluster/join-tokens with desired role/label/ttl.
       Server returns the plaintext token *exactly once* (the DB only
       stores its SHA-256 hash).
    2. Operator runs ``install.sh --join=<token> --primary=<panel-url>``
       on the new box. install.sh POSTs the token to /cluster/join.
    3. Server verifies the token, marks it consumed, returns the
       cluster config the new node needs (DB DSN, Redis URL, MinIO
       creds, internal CA). New node registers itself in `nodes` and
       starts heartbeating.
    4. Cluster page polls /cluster/nodes and the new node appears.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import CurrentUser
from ...auth.permissions import require_admin
from ...config import get_config
from ...db.models.ops import Node, NodeJoinToken
from ...db.session import get_session
from ...schemas.system import NodeRead
from ...services.audit_service import log_audit


router = APIRouter(prefix="/cluster", tags=["cluster"])


NodeRole = Literal["gpu", "app", "sip", "mixed"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NodeReadFull(BaseModel):
    id:                UUID
    hostname:          str
    role:              str
    services:          list[str]
    status:            str
    last_heartbeat_at: datetime | None
    joined_at:         datetime
    drained_at:        datetime | None = None


class JoinTokenCreate(BaseModel):
    role:        NodeRole
    label:       str = Field("", max_length=200)
    ttl_minutes: int = Field(60, ge=5, le=1440)


class JoinTokenRead(BaseModel):
    id:          UUID
    role:        str
    label:       str
    created_at:  datetime
    expires_at:  datetime
    consumed_at: datetime | None = None


class JoinTokenCreated(JoinTokenRead):
    """Returned only on creation — includes the plaintext token *once*."""
    token:           str
    install_command: str


class JoinRequest(BaseModel):
    token:    str = Field(..., min_length=20, max_length=512)
    hostname: str = Field(..., min_length=1, max_length=253)


class JoinResult(BaseModel):
    node_id:    UUID
    role:       str
    cluster_config: dict
    """Bootstrap config the new node uses to reach shared services
    (Postgres DSN, Redis URL, MinIO endpoint+creds, panel public URL)."""


class NodeRoleUpdate(BaseModel):
    role: NodeRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _to_full(n: Node) -> NodeReadFull:
    return NodeReadFull(
        id=n.id, hostname=n.hostname, role=n.role,
        services=list(n.services or []),
        status=n.status,
        last_heartbeat_at=n.last_heartbeat_at,
        joined_at=n.joined_at,
        drained_at=getattr(n, "drained_at", None),
    )


def _cluster_config_for_new_node() -> dict:
    """Return the bootstrap config a new node needs to wire itself up.

    The new node's ``install.sh --join`` writes these into
    ``/etc/aipanel/aipanel.conf`` so it points at shared infra instead
    of bringing up its own Postgres/Redis/MinIO.
    """
    cfg = get_config()
    return {
        "panel_public_url": cfg.panel.public_url,
        "database": {
            "host": cfg.database.host, "port": cfg.database.port,
            "name": cfg.database.name, "user": cfg.database.user,
        },
        "redis":    {"host": cfg.redis.host, "port": cfg.redis.port,
                     "db":   cfg.redis.db},
        "minio":    {"endpoint": cfg.minio.endpoint,
                     "secure": cfg.minio.secure,
                     "bucket_recordings": cfg.minio.bucket_recordings,
                     "bucket_transcripts": cfg.minio.bucket_transcripts,
                     "bucket_kb": cfg.minio.bucket_kb,
                     "bucket_voices": cfg.minio.bucket_voices},
        # Secrets (DB password, Redis password, MinIO keys) are NOT
        # returned over the wire. The operator copies them out of
        # /etc/aipanel/secrets.env on the primary, or we use a short-
        # lived secret-bootstrap mechanism. install.sh prompts.
    }


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("/nodes", response_model=list[NodeReadFull])
async def list_nodes(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: CurrentUser,
) -> list[NodeReadFull]:
    rows = (await session.execute(
        select(Node).order_by(Node.role.asc(), Node.hostname.asc())
    )).scalars().all()
    return [_to_full(n) for n in rows]


@router.get("/health")
async def cluster_health(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: CurrentUser,
) -> dict:
    rows = (await session.execute(
        select(Node).where(Node.status != "down")
    )).scalars().all()
    return {"healthy_nodes": len(rows)}


# ---------------------------------------------------------------------------
# Join token lifecycle
# ---------------------------------------------------------------------------


@router.get("/join-tokens", response_model=list[JoinTokenRead],
            dependencies=[Depends(require_admin)])
async def list_join_tokens(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[JoinTokenRead]:
    """Admin view of all unconsumed + recently consumed tokens."""
    rows = (await session.execute(
        select(NodeJoinToken).order_by(NodeJoinToken.created_at.desc())
                              .limit(50)
    )).scalars().all()
    return [
        JoinTokenRead(
            id=t.id, role=t.role, label=t.label,
            created_at=t.created_at, expires_at=t.expires_at,
            consumed_at=t.consumed_at,
        )
        for t in rows
    ]


@router.post("/join-tokens", response_model=JoinTokenCreated,
             status_code=201, dependencies=[Depends(require_admin)])
async def create_join_token(
    body: JoinTokenCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> JoinTokenCreated:
    raw = "AIPANEL-" + secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=body.ttl_minutes)

    tok = NodeJoinToken(
        token_hash=_hash_token(raw),
        role=body.role,
        label=body.label,
        created_by=user.id,
        expires_at=expires,
    )
    session.add(tok)
    await session.flush()
    await session.refresh(tok)

    cfg = get_config()
    cmd = (
        f"curl -fsSL {cfg.panel.public_url}/install-join.sh | "
        f"sudo bash -s -- "
        f"--token={raw} "
        f"--primary={cfg.panel.public_url} "
        f"--role={body.role}"
    )

    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="cluster.join_token_create",
                    target_type="node_join_token", target_id=tok.id,
                    payload={"role": body.role, "ttl_minutes": body.ttl_minutes})

    return JoinTokenCreated(
        id=tok.id, role=tok.role, label=tok.label,
        created_at=tok.created_at, expires_at=tok.expires_at,
        consumed_at=None,
        token=raw, install_command=cmd,
    )


@router.delete("/join-tokens/{token_id}", status_code=204,
               dependencies=[Depends(require_admin)])
async def revoke_join_token(
    token_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> None:
    tok = await session.get(NodeJoinToken, token_id)
    if tok is None:
        raise HTTPException(status_code=404, detail="token not found")
    await session.delete(tok)
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="cluster.join_token_revoke",
                    target_type="node_join_token", target_id=token_id)


@router.post("/join", response_model=JoinResult)
async def join(
    body: JoinRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JoinResult:
    """Called by ``install.sh --join`` on the new node. NOT admin-gated:
    the bearer is the join token itself, validated below."""
    h = _hash_token(body.token)
    tok = (await session.execute(
        select(NodeJoinToken).where(NodeJoinToken.token_hash == h)
    )).scalar_one_or_none()
    if tok is None:
        raise HTTPException(status_code=403, detail="invalid token")
    if tok.consumed_at is not None:
        raise HTTPException(status_code=409, detail="token already used")
    if tok.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="token expired")

    # Refuse to register two nodes with the same hostname.
    existing = (await session.execute(
        select(Node).where(Node.hostname == body.hostname)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"a node with hostname '{body.hostname}' is already registered",
        )

    # Default services per role.
    services_for = {
        "gpu":   ["aipanel-llm", "aipanel-stt", "aipanel-tts"],
        "app":   ["aipanel-web", "aipanel-jobs", "aipanel-workers",
                  "aipanel-session-mgr"],
        "sip":   ["aipanel-sip"],
        "mixed": ["aipanel-web", "aipanel-jobs", "aipanel-workers",
                  "aipanel-session-mgr", "aipanel-llm",
                  "aipanel-stt", "aipanel-tts", "aipanel-sip"],
    }
    node = Node(
        hostname=body.hostname,
        role=tok.role,
        services=services_for.get(tok.role, []),
        status="joining",
    )
    session.add(node)
    await session.flush()
    await session.refresh(node)

    tok.consumed_at = datetime.now(timezone.utc)
    tok.consumed_by_node = node.id
    await session.flush()

    # No tenant_id available — this is service-to-service, not user.
    await log_audit(session, user_id=None, tenant_id=None,
                    action="cluster.node_joined", target_type="node",
                    target_id=node.id,
                    payload={"hostname": body.hostname, "role": tok.role,
                             "remote_addr": (request.client.host
                                             if request.client else None)})

    return JoinResult(
        node_id=node.id,
        role=tok.role,
        cluster_config=_cluster_config_for_new_node(),
    )


# ---------------------------------------------------------------------------
# Per-node management — drain + remove + role change
# ---------------------------------------------------------------------------


@router.post("/nodes/{node_id}/drain",
             dependencies=[Depends(require_admin)])
async def drain_node(
    node_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> dict:
    """Mark a node as drained. The worker on it stops accepting new
    jobs but finishes in-flight ones gracefully. The next /heartbeat
    from this node sees drained_at != NULL and shuts itself down."""
    n = await session.get(Node, node_id)
    if n is None:
        raise HTTPException(status_code=404, detail="node not found")
    n.drained_at = datetime.now(timezone.utc)
    n.status = "draining"
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="cluster.node_drain",
                    target_type="node", target_id=node_id)
    return {"ok": True, "drained_at": n.drained_at.isoformat()}


@router.delete("/nodes/{node_id}", status_code=204,
               dependencies=[Depends(require_admin)])
async def remove_node(
    node_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> None:
    n = await session.get(Node, node_id)
    if n is None:
        raise HTTPException(status_code=404, detail="node not found")
    if n.role == "primary":
        raise HTTPException(
            status_code=400,
            detail="cannot remove the primary node",
        )
    if n.status not in ("down", "drained", "draining"):
        raise HTTPException(
            status_code=400,
            detail=("node must be drained first — POST /nodes/{id}/drain "
                    "and wait for status=drained, then DELETE"),
        )
    await session.delete(n)
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="cluster.node_remove",
                    target_type="node", target_id=node_id,
                    payload={"hostname": n.hostname})


@router.patch("/nodes/{node_id}", response_model=NodeReadFull,
              dependencies=[Depends(require_admin)])
async def update_node_role(
    node_id: UUID,
    body: NodeRoleUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
) -> NodeReadFull:
    n = await session.get(Node, node_id)
    if n is None:
        raise HTTPException(status_code=404, detail="node not found")
    if n.role == "primary":
        raise HTTPException(
            status_code=400,
            detail="cannot change the role of the primary node",
        )
    old = n.role
    n.role = body.role
    await log_audit(session, user_id=user.id, tenant_id=user.tenant_id,
                    action="cluster.node_role_change",
                    target_type="node", target_id=node_id,
                    payload={"from": old, "to": body.role})
    return _to_full(n)
