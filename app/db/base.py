from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for database models used by Alembic migrations."""
