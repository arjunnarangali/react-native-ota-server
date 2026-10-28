import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import check_database_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz/live", summary="Check that the API process is running")
def liveness() -> dict[str, str]:
    """Liveness does not depend on PostgreSQL being available."""
    return {"status": "alive"}


@router.get("/healthz/ready", summary="Check that the API can use PostgreSQL")
def readiness() -> dict[str, str]:
    """Readiness succeeds only when the configured database can be queried."""
    try:
        check_database_connection()
    except SQLAlchemyError as exc:
        logger.warning("Database readiness check failed: %s", exc.__class__.__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc

    return {"status": "ready", "database": "connected"}
