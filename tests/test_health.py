from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import health
from app.main import app

client = TestClient(app)


def test_liveness_does_not_require_database() -> None:
    response = client.get("/healthz/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_when_database_is_available(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database_connection", lambda: None)

    response = client.get("/healthz/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "connected"}


def test_readiness_when_database_is_unavailable(monkeypatch) -> None:
    def fail_database_check() -> None:
        raise SQLAlchemyError("connection failed")

    monkeypatch.setattr(health, "check_database_connection", fail_database_check)

    response = client.get("/healthz/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
