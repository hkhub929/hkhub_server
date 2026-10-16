from fastapi import APIRouter

from app.api.routes import commute, company_observation, education, health, rent

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(education.router, prefix="/education", tags=["education"])
api_router.include_router(commute.router, prefix="/commute", tags=["commute"])
api_router.include_router(rent.router, prefix="/rent", tags=["rent"])
api_router.include_router(company_observation.router, prefix="/company-observation", tags=["company-observation"])
