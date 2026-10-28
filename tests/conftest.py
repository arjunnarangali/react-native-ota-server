import base64
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA, SECP256R1, generate_private_key
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import database_session
from app.api.routes.releases import get_artifact_storage
from app.api.schemas.releases import ReleaseManifest
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.main import app
from app.services.artifact_storage import LocalArtifactStorage
from app.services.bundle_package import build_deterministic_package
from app.services.manifest import canonical_manifest
from app.models import OtaRelease  # noqa: F401 - register model metadata for tests


@dataclass
class SignedBundle:
    bundle_path: Path
    manifest_bytes: bytes
    signature: str
    release_id: str


@pytest.fixture
def release_environment(tmp_path: Path) -> Generator[dict, None, None]:
    private_key = generate_private_key(SECP256R1())
    public_key_path = tmp_path / "publisher-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings = Settings(
        database_url="sqlite+pysqlite://",
        ota_admin_token="test-admin-token",
        ota_signing_public_key_path=public_key_path,
        ota_storage_dir=tmp_path / "stored-artifacts",
    )
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_database() -> Generator[Session, None, None]:
        with test_sessions() as session:
            yield session

    storage = LocalArtifactStorage(settings.ota_storage_dir)
    app.dependency_overrides[database_session] = override_database
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_artifact_storage] = lambda: storage

    with TestClient(app) as client:
        yield {
            "client": client,
            "private_key": private_key,
            "settings": settings,
            "storage": storage,
            "tmp_path": tmp_path,
        }

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_signed_bundle(
    environment: dict,
    version: int,
    *,
    app_id: str = "com.ota",
    runtime_version: str = "rn-0.88.0-android-1",
) -> SignedBundle:
    temporary_path: Path = environment["tmp_path"]
    bundle_source = temporary_path / f"bundle-{version}.js"
    bundle_source.write_text(f"console.log('OTA release {version}');\n", encoding="utf-8")
    assets_dir = temporary_path / f"assets-{version}"
    assets_dir.mkdir(exist_ok=True)
    (assets_dir / f"image-{version}.png").write_bytes(bytes([version, 2, 3]))
    bundle_path = temporary_path / f"release-{version}.zip"
    build_deterministic_package(bundle_source, assets_dir, bundle_path)

    manifest = ReleaseManifest(
        release_id=uuid4(),
        platform="android",
        app_id=app_id,
        runtime_version=runtime_version,
        version=version,
        artifact_sha256=__import__("hashlib").sha256(bundle_path.read_bytes()).hexdigest(),
        artifact_size_bytes=bundle_path.stat().st_size,
        created_at=datetime.now(timezone.utc),
    )
    manifest_bytes = canonical_manifest(manifest)
    signature = base64.b64encode(
        environment["private_key"].sign(manifest_bytes, ECDSA(hashes.SHA256()))
    ).decode("ascii")
    return SignedBundle(
        bundle_path=bundle_path,
        manifest_bytes=manifest_bytes,
        signature=signature,
        release_id=str(manifest.release_id),
    )


@pytest.fixture
def signed_bundle_factory(release_environment):
    return lambda version, **kwargs: make_signed_bundle(release_environment, version, **kwargs)
