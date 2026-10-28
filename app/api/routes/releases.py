import logging
import re
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import database_session, require_admin
from app.api.schemas.releases import (
    AdminReleaseResponse,
    ReleaseManifest,
    RolloutRequest,
    UpdateCheckRequest,
    UpdateCheckResponse,
    UpdateRelease,
)
from app.core.config import Settings, get_settings
from app.models.release import OtaRelease
from app.services.artifact_storage import LocalArtifactStorage, StagedArtifact
from app.services.bundle_package import BundlePackageError, validate_ota_package
from app.services.manifest import ManifestError, parse_and_verify_manifest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["OTA releases"])
CHANNEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def get_artifact_storage(
    settings: Settings = Depends(get_settings),
) -> LocalArtifactStorage:
    return LocalArtifactStorage(settings.ota_storage_dir)


def get_release_manifest(release: OtaRelease) -> ReleaseManifest:
    return ReleaseManifest.model_validate(release.manifest_json)


def to_admin_response(release: OtaRelease) -> AdminReleaseResponse:
    return AdminReleaseResponse(
        release_id=UUID(release.release_id),
        manifest=get_release_manifest(release),
        signature=release.signature,
        channel=release.channel,
        state=release.state,
        rollout_percentage=release.rollout_percentage,
        is_rollback=release.is_rollback,
        published_at=release.published_at,
    )


def validate_channel(channel: str) -> str:
    if not CHANNEL_PATTERN.fullmatch(channel):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Channel must use lowercase letters, numbers, dots, underscores, or hyphens",
        )
    return channel


def installation_in_rollout(release_id: str, installation_id: UUID, percentage: int) -> bool:
    if percentage <= 0:
        return False
    if percentage >= 100:
        return True
    import hashlib

    bucket = int(
        hashlib.sha256(f"{release_id}:{installation_id}".encode("utf-8")).hexdigest()[:8], 16
    ) % 100
    return bucket < percentage


@router.post(
    "/updates/check",
    response_model=UpdateCheckResponse,
    summary="Find an eligible update for this installed app",
)
def check_for_update(
    payload: UpdateCheckRequest,
    request: Request,
    database: Annotated[Session, Depends(database_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UpdateCheckResponse:
    releases = database.scalars(
        select(OtaRelease)
        .where(
            OtaRelease.platform == payload.platform,
            OtaRelease.app_id == payload.app_id,
            OtaRelease.runtime_version == payload.runtime_version,
            OtaRelease.channel == payload.channel,
            OtaRelease.state == "active",
        )
        .order_by(OtaRelease.version.desc())
    ).all()

    for release in releases:
        if payload.failed_release_id is not None and release.release_id == str(payload.failed_release_id):
            continue
        if release.version == payload.current_version:
            continue
        if release.version < payload.current_version and not release.is_rollback:
            continue
        if not installation_in_rollout(
            release.release_id, payload.installation_id, release.rollout_percentage
        ):
            continue

        return UpdateCheckResponse(
            update_available=True,
            release=UpdateRelease(
                manifest=get_release_manifest(release),
                signature=release.signature,
                channel=release.channel,
                rollout_percentage=release.rollout_percentage,
                action=(
                    "rollback"
                    if release.is_rollback and payload.current_version > release.version
                    else "update"
                ),
                download_url=(
                    f"{settings.ota_public_base_url}/api/v1/releases/{release.release_id}/bundle"
                    if settings.ota_public_base_url
                    else str(request.url_for("download_release_bundle", release_id=release.release_id))
                ),
            ),
        )

    return UpdateCheckResponse(update_available=False)


@router.get(
    "/releases/{release_id}/bundle",
    name="download_release_bundle",
    summary="Download a published immutable bundle package",
)
def download_release_bundle(
    release_id: UUID,
    database: Annotated[Session, Depends(database_session)],
    storage: Annotated[LocalArtifactStorage, Depends(get_artifact_storage)],
) -> FileResponse:
    release = database.get(OtaRelease, str(release_id))
    if release is None or release.state == "disabled":
        raise HTTPException(status_code=404, detail="Release bundle not found")

    path = storage.artifact_path(release_id)
    if not path.is_file():
        logger.error("Artifact missing for published release %s", release_id)
        raise HTTPException(status_code=404, detail="Release bundle not found")

    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"ota-{release_id}.zip",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post(
    "/admin/releases",
    response_model=AdminReleaseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    summary="Publish a signed Android bundle",
)
async def publish_release(
    manifest: Annotated[str, Form()],
    signature: Annotated[str, Form()],
    channel: Annotated[str, Form()],
    bundle: Annotated[UploadFile, File()],
    database: Annotated[Session, Depends(database_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[LocalArtifactStorage, Depends(get_artifact_storage)],
    rollout_percentage: Annotated[int, Form(ge=0, le=100)] = 100,
) -> AdminReleaseResponse:
    channel = validate_channel(channel)
    try:
        manifest_bytes = manifest.encode("utf-8")
        signed_manifest, verified_signature = parse_and_verify_manifest(
            manifest_bytes,
            signature.strip(),
            str(settings.ota_signing_public_key_path),
        )
    except ManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("OTA signing verification is not configured")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if signed_manifest.artifact_size_bytes > settings.ota_max_bundle_size_bytes:
        raise HTTPException(status_code=413, detail="Bundle exceeds the configured upload limit")

    highest_version = database.scalar(
        select(func.max(OtaRelease.version)).where(
            OtaRelease.platform == signed_manifest.platform,
            OtaRelease.app_id == signed_manifest.app_id,
            OtaRelease.runtime_version == signed_manifest.runtime_version,
            OtaRelease.channel == channel,
        )
    )
    if highest_version is not None and signed_manifest.version <= highest_version:
        raise HTTPException(
            status_code=409,
            detail=f"Release version must be greater than {highest_version} for this app/runtime/channel",
        )

    staged: StagedArtifact | None = None
    committed = False
    try:
        staged = await storage.stage_upload(
            bundle, signed_manifest.release_id, settings.ota_max_bundle_size_bytes
        )
        if staged.size_bytes != signed_manifest.artifact_size_bytes:
            raise HTTPException(status_code=400, detail="Bundle size does not match signed manifest")
        if staged.sha256 != signed_manifest.artifact_sha256:
            raise HTTPException(status_code=400, detail="Bundle hash does not match signed manifest")
        try:
            validate_ota_package(staged.temporary_path, settings.ota_max_bundle_size_bytes * 5)
        except BundlePackageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        active_releases = database.scalars(
            select(OtaRelease)
            .where(
                OtaRelease.platform == signed_manifest.platform,
                OtaRelease.app_id == signed_manifest.app_id,
                OtaRelease.runtime_version == signed_manifest.runtime_version,
                OtaRelease.channel == channel,
                OtaRelease.state == "active",
            )
            .with_for_update()
        ).all()
        for active in active_releases:
            active.state = "archived"
            active.is_rollback = False
        database.flush()

        release = OtaRelease(
            release_id=str(signed_manifest.release_id),
            platform=signed_manifest.platform,
            app_id=signed_manifest.app_id,
            runtime_version=signed_manifest.runtime_version,
            version=signed_manifest.version,
            channel=channel,
            state="active",
            rollout_percentage=rollout_percentage,
            is_rollback=False,
            artifact_sha256=signed_manifest.artifact_sha256,
            artifact_size_bytes=signed_manifest.artifact_size_bytes,
            manifest_json=signed_manifest.model_dump(mode="json"),
            signature=verified_signature,
            created_at=signed_manifest.created_at,
        )
        database.add(release)
        staged.publish()
        database.commit()
        committed = True
        database.refresh(release)
        return to_admin_response(release)
    except FileExistsError as exc:
        database.rollback()
        if staged is not None and not committed:
            staged.discard()
        raise HTTPException(status_code=409, detail="Artifact already exists") from exc
    except IntegrityError as exc:
        database.rollback()
        if staged is not None and not committed:
            staged.discard()
        raise HTTPException(status_code=409, detail="Release ID or version already exists") from exc
    except Exception:
        database.rollback()
        if staged is not None and not committed:
            staged.discard()
        raise
    finally:
        await bundle.close()


@router.get(
    "/admin/releases",
    response_model=list[AdminReleaseResponse],
    dependencies=[Depends(require_admin)],
    summary="List published releases",
)
def list_releases(
    database: Annotated[Session, Depends(database_session)],
) -> list[AdminReleaseResponse]:
    releases = database.scalars(
        select(OtaRelease).order_by(OtaRelease.published_at.desc(), OtaRelease.version.desc())
    ).all()
    return [to_admin_response(release) for release in releases]


@router.patch(
    "/admin/releases/{release_id}/rollout",
    response_model=AdminReleaseResponse,
    dependencies=[Depends(require_admin)],
    summary="Change the active release rollout percentage",
)
def change_rollout(
    release_id: UUID,
    payload: RolloutRequest,
    database: Annotated[Session, Depends(database_session)],
) -> AdminReleaseResponse:
    release = database.get(OtaRelease, str(release_id))
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.state != "active":
        raise HTTPException(status_code=409, detail="Only an active release can change rollout")

    release.rollout_percentage = payload.rollout_percentage
    database.commit()
    database.refresh(release)
    return to_admin_response(release)


@router.post(
    "/admin/releases/{release_id}/disable",
    response_model=AdminReleaseResponse,
    dependencies=[Depends(require_admin)],
    summary="Stop serving a release to update clients",
)
def disable_release(
    release_id: UUID,
    database: Annotated[Session, Depends(database_session)],
) -> AdminReleaseResponse:
    release = database.get(OtaRelease, str(release_id))
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    release.state = "disabled"
    release.is_rollback = False
    database.commit()
    database.refresh(release)
    return to_admin_response(release)


@router.post(
    "/admin/releases/{release_id}/rollback",
    response_model=AdminReleaseResponse,
    dependencies=[Depends(require_admin)],
    summary="Make a previous signed release active again",
)
def rollback_release(
    release_id: UUID,
    database: Annotated[Session, Depends(database_session)],
) -> AdminReleaseResponse:
    target = database.get(OtaRelease, str(release_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if target.state == "active":
        raise HTTPException(status_code=409, detail="Release is already active")

    current_active = database.scalars(
        select(OtaRelease)
        .where(
            OtaRelease.platform == target.platform,
            OtaRelease.app_id == target.app_id,
            OtaRelease.runtime_version == target.runtime_version,
            OtaRelease.channel == target.channel,
            OtaRelease.state == "active",
        )
        .with_for_update()
    ).all()
    for release in current_active:
        release.state = "archived"
        release.is_rollback = False
    database.flush()

    target.state = "active"
    target.rollout_percentage = 100
    target.is_rollback = True
    database.commit()
    database.refresh(target)
    return to_admin_response(target)
