from argparse import Namespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

from app.services.bundle_package import build_deterministic_package
from app.services.manifest import parse_and_verify_manifest
from tools.ota_signing import sign_manifest


def test_sign_manifest_supports_ios_platform_and_verifies_signature(tmp_path):
    private_key = generate_private_key(SECP256R1())
    private_key_path = tmp_path / "publisher-private.pem"
    public_key_path = tmp_path / "publisher-public.pem"
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    bundle = tmp_path / "main.jsbundle"
    bundle.write_bytes(bytes((0xC6, 0x1F, 0xBC, 0x03)) + b"test hermes payload")
    assets = tmp_path / "assets"
    assets.mkdir()
    package = tmp_path / "ios.zip"
    build_deterministic_package(
        bundle, assets, package, bundle_format="hermes-bytecode", platform="ios"
    )
    manifest_output = tmp_path / "ios-manifest.json"
    signature_output = tmp_path / "ios-signature.txt"

    sign_manifest(
        Namespace(
            bundle=package,
            private_key=private_key_path,
            platform="ios",
            app_id="com.example.ios",
            runtime_version="rn-0.88-ios-v1",
            version=1,
            release_id=None,
            manifest_output=manifest_output,
            signature_output=signature_output,
        )
    )

    manifest, signature = parse_and_verify_manifest(
        manifest_output.read_bytes(), signature_output.read_text(encoding="ascii").strip(), str(public_key_path)
    )
    assert manifest.platform == "ios"
    assert manifest.app_id == "com.example.ios"
    assert manifest.runtime_version == "rn-0.88-ios-v1"
    assert signature == signature_output.read_text(encoding="ascii").strip()
