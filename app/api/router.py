from fastapi import APIRouter

from app.api.routes import commute, education, health

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(education.router, prefix="/education", tags=["education"])
api_router.include_router(commute.router, prefix="/commute", tags=["commute"])
