"""
Top-level API router.
Mounts both versioned routers so FastAPI serves /api/v1/* and /api/v2/* concurrently.
"""
from fastapi import APIRouter
from app.api.v1.routes import v1_router
from app.api.v2.routes import v2_router

api_router = APIRouter()

api_router.include_router(v1_router, prefix="/v1")
api_router.include_router(v2_router, prefix="/v2")
