import argparse
import base64
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDSA,
    EllipticCurvePrivateKey,
    SECP256R1,
    generate_private_key,
)

from app.api.schemas.releases import ReleaseManifest
from app.services.bundle_package import sha256_file, validate_ota_package
from app.services.manifest import canonical_manifest


def create_key_file(path: Path, content: bytes, mode: int, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    descriptor = os.open(path, flags, mode)
    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(content)
        key_file.flush()
        os.fsync(key_file.fileno())
    os.chmod(path, mode)


def generate_keys(args: argparse.Namespace) -> None:
    private_key_path: Path = args.private_key
    public_key_path: Path = args.public_key
    if private_key_path.resolve() == public_key_path.resolve():
        raise SystemExit("Private and public key paths must be different")

    private_key = generate_private_key(SECP256R1())
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # The private key is local signing authority: create it owner-readable only.
    create_key_file(private_key_path, private_bytes, 0o600, args.force)
    try:
        create_key_file(public_key_path, public_bytes, 0o644, args.force)
    except Exception:
        private_key_path.unlink(missing_ok=True)
        raise

    print(f"Private signing key: {private_key_path}")
    print(f"Public verification key: {public_key_path}")
    print("Keep the private key out of Git and out of the Android app.")


def sign_manifest(args: argparse.Namespace) -> None:
    bundle_path: Path = args.bundle
    if not bundle_path.is_file():
        raise SystemExit(f"Bundle not found: {bundle_path}")
    try:
        validate_ota_package(bundle_path, max_uncompressed_bytes=500 * 1024 * 1024)
        with zipfile.ZipFile(bundle_path) as archive:
            package_manifest = json.loads(archive.read("ota-manifest.json"))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"Bundle is not a valid OTA package: {exc}") from exc
    if package_manifest["entrypoint_format"] != "hermes-bytecode":
        raise SystemExit("Android OTA releases must contain a Hermes bytecode bundle")

    with args.private_key.open("rb") as key_file:
        private_key = serialization.load_pem_private_key(key_file.read(), password=None)
    if not isinstance(private_key, EllipticCurvePrivateKey) or not isinstance(
        private_key.curve, SECP256R1
    ):
        raise SystemExit("The publisher private key must use P-256 ECDSA")

    manifest = ReleaseManifest(
        manifest_version=1,
        release_id=args.release_id or uuid4(),
        platform="android",
        app_id=args.app_id,
        runtime_version=args.runtime_version,
        version=args.version,
        artifact_sha256=sha256_file(bundle_path),
        artifact_size_bytes=bundle_path.stat().st_size,
        created_at=datetime.now(timezone.utc),
    )
    manifest_bytes = canonical_manifest(manifest)
    signature = base64.b64encode(
        private_key.sign(manifest_bytes, ECDSA(hashes.SHA256()))
    ).decode("ascii")

    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.signature_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_bytes(manifest_bytes)
    args.signature_output.write_text(signature + "\n", encoding="ascii")
    print(f"Manifest: {args.manifest_output}")
    print(f"Signature: {args.signature_output}")
    print(f"Release ID: {manifest.release_id}")
    print(f"Version: {manifest.version}")
    print(f"SHA-256: {manifest.artifact_sha256}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OTA signing keys or sign a release manifest.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    key_parser = subparsers.add_parser("generate-keys", help="Generate a P-256 ECDSA publisher keypair")
    key_parser.add_argument("--private-key", type=Path, required=True)
    key_parser.add_argument("--public-key", type=Path, required=True)
    key_parser.add_argument("--force", action="store_true", help="Replace existing key files")
    key_parser.set_defaults(handler=generate_keys)

    sign_parser = subparsers.add_parser("sign-manifest", help="Hash a bundle and sign its release manifest")
    sign_parser.add_argument("--bundle", type=Path, required=True)
    sign_parser.add_argument("--private-key", type=Path, required=True)
    sign_parser.add_argument("--app-id", required=True)
    sign_parser.add_argument("--runtime-version", required=True)
    sign_parser.add_argument("--version", type=int, required=True)
    sign_parser.add_argument("--release-id", type=UUID)
    sign_parser.add_argument("--manifest-output", type=Path, required=True)
    sign_parser.add_argument("--signature-output", type=Path, required=True)
    sign_parser.set_defaults(handler=sign_manifest)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
