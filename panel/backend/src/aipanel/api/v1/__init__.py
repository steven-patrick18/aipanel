"""v1 routes — composed by api/v1/router.py."""

from fastapi import APIRouter

from . import (
    agents,
    analytics,
    auth,
    calls,
    campaigns,
    cluster,
    deployments,
    kb,
    methodologies,
    system,
    tenants,
    updates,
    vicidial_servers,
    voices,
)

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(tenants.router)
router.include_router(agents.router)
router.include_router(campaigns.router)
router.include_router(methodologies.router)
router.include_router(voices.router)
router.include_router(kb.router)
router.include_router(vicidial_servers.router)
router.include_router(deployments.router)
router.include_router(calls.router)
router.include_router(analytics.router)
router.include_router(cluster.router)
router.include_router(system.router)
router.include_router(updates.router)
