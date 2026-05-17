"""
API v1 — frozen baseline.
Do NOT modify these routes. Bug fixes only via the patch process.
New features and changed response shapes go into v2.
"""
from fastapi import APIRouter
from app.api.v1 import auth, metadata, arb_submissions, reviews, artefacts, agent, admin

v1_router = APIRouter()

v1_router.include_router(auth.router,            prefix="/auth",        tags=["v1 / authentication"])
v1_router.include_router(metadata.router,        prefix="/metadata",    tags=["v1 / metadata"])
v1_router.include_router(arb_submissions.router, prefix="/submissions", tags=["v1 / submissions"])
v1_router.include_router(reviews.router,         prefix="/reviews",     tags=["v1 / reviews"])
v1_router.include_router(agent.router,           prefix="/agent",       tags=["v1 / agent"])
v1_router.include_router(artefacts.router,       prefix="/artefacts",   tags=["v1 / artefacts"])
v1_router.include_router(admin.router,           prefix="/admin",       tags=["v1 / admin"])
