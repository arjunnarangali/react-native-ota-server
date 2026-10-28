import base64
import binascii
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA, EllipticCurvePublicKey, SECP256R1
from pydantic import ValidationError

from app.api.schemas.releases import ReleaseManifest


class ManifestError(ValueError):
    """Raised when a release manifest is malformed or not publisher-signed."""


def canonical_json(value: Any) -> bytes:
    """Serialize JSON consistently so publishers sign exactly the bytes sent."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_manifest(manifest: ReleaseManifest) -> bytes:
    return canonical_json(manifest.model_dump(mode="json"))


def parse_and_verify_manifest(
    manifest_bytes: bytes,
    signature_b64: str,
    public_key_path: str,
) -> tuple[ReleaseManifest, str]:
    try:
        raw_value = json.loads(manifest_bytes)
        manifest = ReleaseManifest.model_validate(raw_value)
        canonical = canonical_manifest(manifest)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise ManifestError("Manifest JSON is invalid or not canonical") from exc

    if canonical != manifest_bytes:
        raise ManifestError("Manifest must use canonical JSON encoding")

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ManifestError("Signature must be valid base64") from exc

    try:
        with open(public_key_path, "rb") as key_file:
            public_key = serialization.load_pem_public_key(key_file.read())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Publisher public signing key is unavailable") from exc

    if not isinstance(public_key, EllipticCurvePublicKey) or not isinstance(
        public_key.curve, SECP256R1
    ):
        raise RuntimeError("Publisher public key must use P-256 ECDSA")

    try:
        public_key.verify(signature, manifest_bytes, ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ManifestError("Release manifest signature is invalid") from exc

    return manifest, signature_b64
