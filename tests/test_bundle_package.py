import stat
import zipfile

import pytest

from app.services.bundle_package import (
    BundlePackageError,
    build_deterministic_package,
    validate_ota_package,
)


def test_package_is_deterministic_and_manifest_covers_all_assets(tmp_path):
    bundle = tmp_path / "index.android.bundle"
    bundle.write_bytes(bytes((0xC6, 0x1F, 0xBC, 0x03)) + b"hello")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "image.png").write_bytes(b"image bytes")
    (assets / "nested").mkdir()
    (assets / "nested" / "font.ttf").write_bytes(b"font bytes")

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build_deterministic_package(bundle, assets, first, bundle_format="hermes-bytecode")
    build_deterministic_package(bundle, assets, second, bundle_format="hermes-bytecode")

    assert first.read_bytes() == second.read_bytes()
    validate_ota_package(first, max_uncompressed_bytes=1024)


def test_package_rejects_path_traversal(tmp_path):
    malicious_package = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_package, "w") as archive:
        archive.writestr("../outside.txt", "not allowed")
        archive.writestr("ota-manifest.json", "{}")

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
    bundle.write_bytes(bytes((0xC6, 0x1F, 0xBC, 0x03)) + b"no assets")
    assets = tmp_path / "assets"
    assets.mkdir()
    output = tmp_path / "no-assets.zip"

    result = build_deterministic_package(bundle, assets, output, bundle_format="hermes-bytecode")

    assert result["asset_count"] == 0
    validate_ota_package(output, max_uncompressed_bytes=1024)


@pytest.mark.parametrize("platform,entrypoint", [("android", "index.android.bundle"), ("ios", "main.jsbundle")])
def test_package_uses_platform_entrypoint_and_rejects_cross_platform_validation(tmp_path, platform, entrypoint):
    bundle = tmp_path / entrypoint
    bundle.write_bytes(bytes((0xC6, 0x1F, 0xBC, 0x03)) + platform.encode())
    assets = tmp_path / f"assets-{platform}"
    assets.mkdir()
    output = tmp_path / f"{platform}.zip"

    build_deterministic_package(
        bundle, assets, output, bundle_format="hermes-bytecode", platform=platform
    )
    validate_ota_package(output, max_uncompressed_bytes=1024, platform=platform)
    other_platform = "ios" if platform == "android" else "android"
    with pytest.raises(BundlePackageError, match="entrypoint"):
        validate_ota_package(output, max_uncompressed_bytes=1024, platform=other_platform)


def test_package_rejects_javascript_source_format(tmp_path):
    bundle = tmp_path / "index.android.bundle"
    bundle.write_bytes(b"javascript source")
    assets = tmp_path / "assets"
    assets.mkdir()
    output = tmp_path / "source.zip"
    build_deterministic_package(bundle, assets, output, bundle_format="javascript-source")

    with pytest.raises(BundlePackageError, match="Hermes bytecode"):
        validate_ota_package(output, max_uncompressed_bytes=1024)


def test_package_rejects_invalid_hermes_header(tmp_path):
    bundle = tmp_path / "main.jsbundle"
    bundle.write_bytes(b"not hermes bytecode")
    assets = tmp_path / "assets"
    assets.mkdir()
    output = tmp_path / "bad-header.zip"
    build_deterministic_package(
        bundle, assets, output, bundle_format="hermes-bytecode", platform="ios"
    )

    with pytest.raises(BundlePackageError, match="Hermes bytecode header"):
        validate_ota_package(output, max_uncompressed_bytes=1024, platform="ios")


def test_package_rejects_symlink_entries(tmp_path):
    package = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("assets/link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(link, "outside")
        archive.writestr("ota-manifest.json", "{}")

    with pytest.raises(BundlePackageError, match="symbolic links"):
        validate_ota_package(package, max_uncompressed_bytes=1024)


def test_package_rejects_duplicate_entries(tmp_path):
    package = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("index.android.bundle", "one")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("index.android.bundle", "two")

    with pytest.raises(BundlePackageError, match="duplicate paths"):
        validate_ota_package(package, max_uncompressed_bytes=1024)


def test_package_rejects_undeclared_files(tmp_path):
    bundle = tmp_path / "index.android.bundle"
    bundle.write_bytes(bytes((0xC6, 0x1F, 0xBC, 0x03)) + b"bundle")
    assets = tmp_path / "assets"
    assets.mkdir()
    original = tmp_path / "valid.zip"
    build_deterministic_package(bundle, assets, original, bundle_format="hermes-bytecode")
    malformed = tmp_path / "undeclared.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(malformed, "w") as target:
        for entry in source.infolist():
            target.writestr(entry.filename, source.read(entry.filename))
        target.writestr("extra.js", "not declared")

    with pytest.raises(BundlePackageError, match="not declared"):
        validate_ota_package(malformed, max_uncompressed_bytes=1024)


def test_package_rejects_asset_hash_mismatch(tmp_path):
    bundle = tmp_path / "index.android.bundle"
    bundle.write_bytes(bytes((0xC6, 0x1F, 0xBC, 0x03)) + b"bundle")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "image.png").write_bytes(b"original asset")
    original = tmp_path / "valid-asset.zip"
    build_deterministic_package(bundle, assets, original, bundle_format="hermes-bytecode")
    malformed = tmp_path / "bad-asset.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(malformed, "w") as target:
        for entry in source.infolist():
            contents = b"tampered asset" if entry.filename == "assets/image.png" else source.read(entry.filename)
            target.writestr(entry.filename, contents)

    with pytest.raises(BundlePackageError, match="Asset size does not match|Asset hash does not match"):
        validate_ota_package(malformed, max_uncompressed_bytes=1024)


def test_package_rejects_expanded_size_over_limit(tmp_path):
    bundle = tmp_path / "index.android.bundle"
    bundle.write_bytes(bytes((0xC6, 0x1F, 0xBC, 0x03)) + b"bundle")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "large.dat").write_bytes(b"x" * 128)
    package = tmp_path / "oversized.zip"
    build_deterministic_package(bundle, assets, package, bundle_format="hermes-bytecode")

    with pytest.raises(BundlePackageError, match="uncompressed size"):
        validate_ota_package(package, max_uncompressed_bytes=64)
