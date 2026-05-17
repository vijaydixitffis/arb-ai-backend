from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging
from app.api.router import api_router
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        logger.info(f"[REQUEST] {request.method} {request.url.path} - Started")

        response = await call_next(request)

        duration = time.time() - start_time
        logger.info(f"[REQUEST] {request.method} {request.url.path} - Completed in {duration:.3f}s - Status {response.status_code}")

        return response

app = FastAPI(
    title="ARB AI Agent API",
    description="Architecture Review Board AI Agent Backend",
    version="1.0.0",
    redirect_slashes=False,
)

# Add request logging middleware first
app.add_middleware(RequestLoggingMiddleware)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount versioned API router — serves /api/v1/* and /api/v2/*
app.include_router(api_router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "ARB AI Agent API", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
