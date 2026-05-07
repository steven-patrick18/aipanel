"""ORM models — one file per logical group, all sharing ``Base.metadata``.

Importing this package eagerly registers every model on ``Base`` so Alembic's
autogenerate sees the full schema.
"""

from .agents import Agent, KbDocument, KnowledgeBase, Voice
from .calls import Call, CallEvent
from .campaigns import Campaign
from .ops import AuditLog, Node, SchemaMigration
from .tenants import Tenant, User
from .vici import Deployment, VicidialServer

__all__ = [
    "Tenant", "User",
    "Agent", "Voice", "KnowledgeBase", "KbDocument",
    "VicidialServer", "Deployment",
    "Call", "CallEvent",
    "Campaign",
    "Node", "AuditLog", "SchemaMigration",
]
