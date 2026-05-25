"""
API v2 — active evolution branch.
Start here when adding new endpoints or changing existing response shapes.
v1 routes remain untouched; frontend controls which version it hits via VITE_API_VERSION.
"""
from fastapi import APIRouter
from app.api.v2 import auth, metadata, arb_submissions, reviews, artefacts, agent, admin, adr_register

v2_router = APIRouter()

v2_router.include_router(auth.router,            prefix="/auth",         tags=["v2 / authentication"])
v2_router.include_router(metadata.router,        prefix="/metadata",     tags=["v2 / metadata"])
v2_router.include_router(arb_submissions.router, prefix="/submissions",  tags=["v2 / submissions"])
v2_router.include_router(reviews.router,         prefix="/reviews",      tags=["v2 / reviews"])
v2_router.include_router(agent.router,           prefix="/agent",        tags=["v2 / agent"])
v2_router.include_router(artefacts.router,       prefix="/artefacts",    tags=["v2 / artefacts"])
v2_router.include_router(admin.router,           prefix="/admin",        tags=["v2 / admin"])
v2_router.include_router(adr_register.router,   prefix="/adr-register", tags=["v2 / adr-register"])
