from fastapi import APIRouter
from app.api.endpoints import auth, metadata, arb_submissions, reviews, artefacts, agent, admin

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(metadata.router, prefix="/metadata", tags=["metadata"])
api_router.include_router(arb_submissions.router, prefix="/submissions", tags=["submissions"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(artefacts.router, prefix="/artefacts", tags=["artefacts"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
