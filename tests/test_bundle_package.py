import zipfile

import pytest

from app.services.bundle_package import (
    BundlePackageError,
    build_deterministic_package,
    validate_ota_package,
)


def test_package_is_deterministic_and_manifest_covers_all_assets(tmp_path):
    bundle = tmp_path / "index.android.bundle"
    bundle.write_bytes(b"console.log('hello');")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "image.png").write_bytes(b"image bytes")
    (assets / "nested").mkdir()
    (assets / "nested" / "font.ttf").write_bytes(b"font bytes")

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build_deterministic_package(bundle, assets, first)
    build_deterministic_package(bundle, assets, second)

    assert first.read_bytes() == second.read_bytes()
    validate_ota_package(first, max_uncompressed_bytes=1024)


def test_package_rejects_path_traversal(tmp_path):
    malicious_package = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_package, "w") as archive:
        archive.writestr("../outside.txt", "not allowed")

    with pytest.raises(BundlePackageError, match="unsafe path"):
        validate_ota_package(malicious_package, max_uncompressed_bytes=1024)


def test_package_builder_rejects_asset_names_reserved_for_runtime_files(tmp_path):
    bundle = tmp_path / "bundle.js"
    bundle.write_bytes(b"bundle")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "release-manifest.json").write_text("not an image", encoding="utf-8")

    with pytest.raises(ValueError, match="reserved by the OTA package format"):
        build_deterministic_package(bundle, assets, tmp_path / "reserved.zip")


def test_package_supports_a_bundle_with_no_assets(tmp_path):
    bundle = tmp_path / "bundle.js"
    bundle.write_bytes(b"console.log('no assets');")
    assets = tmp_path / "assets"
    assets.mkdir()
    output = tmp_path / "no-assets.zip"

    result = build_deterministic_package(bundle, assets, output)

    assert result["asset_count"] == 0
    validate_ota_package(output, max_uncompressed_bytes=1024)
