from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ReleaseManifest(BaseModel):
    """Immutable, publisher-signed metadata for one Android bundle artifact."""

    model_config = ConfigDict(extra="forbid")

    manifest_version: Literal[1] = 1
    release_id: UUID
    platform: Literal["android"]
    app_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$", max_length=255)
    runtime_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    version: int = Field(ge=1, le=2_147_483_647)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_size_bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    created_at: AwareDatetime


class UpdateCheckRequest(BaseModel):
    platform: Literal["android"]
    app_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$", max_length=255)
    runtime_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    channel: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    current_version: int = Field(default=0, ge=0, le=2_147_483_647)
    installation_id: UUID
    failed_release_id: UUID | None = None


class UpdateRelease(BaseModel):
    manifest: ReleaseManifest
    signature: str
    channel: str
    rollout_percentage: int
    action: Literal["update", "rollback"]
    download_url: str


class UpdateCheckResponse(BaseModel):
    update_available: bool
    release: UpdateRelease | None = None


class AdminReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    release_id: UUID
    manifest: ReleaseManifest
    signature: str
    channel: str
    state: Literal["active", "archived", "disabled"]
    rollout_percentage: int
    is_rollback: bool
    published_at: datetime


class RolloutRequest(BaseModel):
    rollout_percentage: int = Field(ge=0, le=100)
