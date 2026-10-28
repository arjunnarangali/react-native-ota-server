from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OtaRelease(Base):
    __tablename__ = "ota_releases"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "app_id",
            "runtime_version",
            "channel",
            "version",
            name="uq_ota_release_lane_version",
        ),
        Index(
            "uq_ota_release_one_active_per_lane",
            "platform",
            "app_id",
            "runtime_version",
            "channel",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
    )

    release_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    app_id: Mapped[str] = mapped_column(String(255), nullable=False)
    runtime_version: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    rollout_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_rollback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    manifest_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
