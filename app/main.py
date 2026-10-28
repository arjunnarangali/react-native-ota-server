from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.releases import router as releases_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Self-hosted OTA update service for the React Native learning project.",
)

app.include_router(health_router)
app.include_router(releases_router)
