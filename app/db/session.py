from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """Yield one database session per API request and always close it."""
    with SessionLocal() as session:
        yield session


def check_database_connection() -> None:
    """Run a minimal query to verify that PostgreSQL is reachable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
