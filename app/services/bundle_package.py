import hashlib
import json
import os
import stat
import zipfile
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.services.manifest import canonical_json


class BundlePackageError(ValueError):
    """Raised when an uploaded OTA ZIP does not match the bundle package format."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_deterministic_package(
    bundle_path: Path,
    assets_dir: Path,
    output_path: Path,
    bundle_format: str = "javascript-source",
) -> dict[str, Any]:
    """Package a Metro bundle and assets with stable paths, metadata, and ZIP bytes."""
    if not bundle_path.is_file():
        raise FileNotFoundError(f"React Native bundle not found: {bundle_path}")
    if not assets_dir.is_dir():
        raise FileNotFoundError(f"Metro assets directory not found: {assets_dir}")

    files: dict[str, Path] = {"index.android.bundle": bundle_path}
    asset_metadata: list[dict[str, Any]] = []

    for path in sorted(assets_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symbolic links are not allowed in OTA assets: {path}")
        if not path.is_file():
            continue
        relative_path = path.relative_to(assets_dir).as_posix()
        package_path = f"assets/{relative_path}"
        if relative_path in {
            "index.android.bundle",
            "ota-manifest.json",
            "release-manifest.json",
            "release-signature.txt",
        }:
            raise ValueError(f"Asset path is reserved by the OTA package format: {relative_path}")
        files[package_path] = path
        asset_metadata.append(
            {
                "path": package_path,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    package_manifest = {
        "format_version": 1,
        "entrypoint": "index.android.bundle",
        "entrypoint_format": bundle_format,
        "entrypoint_sha256": sha256_file(bundle_path),
        "assets": asset_metadata,
    }
    package_manifest_bytes = canonical_json(package_manifest)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            entries = {**files, "ota-manifest.json": None}
            for archive_name in sorted(entries):
                source_path = entries[archive_name]
                data = package_manifest_bytes if source_path is None else source_path.read_bytes()
                info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.flag_bits = 0
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return {
        "output": str(output_path),
        "sha256": sha256_file(output_path),
        "size_bytes": output_path.stat().st_size,
        "asset_count": len(asset_metadata),
    }


def validate_ota_package(package_path: Path, max_uncompressed_bytes: int) -> None:
    """Reject unsafe ZIP paths, oversized expansion, or mismatched internal asset hashes."""
    try:
        with zipfile.ZipFile(package_path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise BundlePackageError("Bundle package contains duplicate paths")
            if sum(entry.file_size for entry in entries) > max_uncompressed_bytes:
                raise BundlePackageError("Bundle expands beyond the allowed uncompressed size")

            files: dict[str, zipfile.ZipInfo] = {}
            for entry in entries:
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise BundlePackageError("Bundle package uses an unsupported compression method")
                if entry.flag_bits & 0x1:
                    raise BundlePackageError("Encrypted bundle package entries are not supported")
                if entry.is_dir():
                    entry_name = entry.filename[:-1]
                else:
                    entry_name = entry.filename
                path = PurePosixPath(entry_name)
                if (
                    path.is_absolute()
                    or path.as_posix() != entry_name
                    or (path.parts and ":" in path.parts[0])
                    or "\\" in entry.filename
                    or any(part in ("", ".", "..") for part in path.parts)
                ):
                    raise BundlePackageError("Bundle package contains an unsafe path")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise BundlePackageError("Bundle package cannot contain symbolic links")
                if entry.is_dir():
                    continue
                files[entry.filename] = entry

            manifest_name = "ota-manifest.json"
            entrypoint = "index.android.bundle"
            if manifest_name not in files or entrypoint not in files:
                raise BundlePackageError("Bundle package is missing its manifest or entrypoint")

            internal_manifest = json.loads(archive.read(manifest_name))
            if internal_manifest.get("format_version") != 1:
                raise BundlePackageError("Unsupported OTA package format")
            if internal_manifest.get("entrypoint") != entrypoint:
                raise BundlePackageError("OTA package entrypoint is invalid")
            if internal_manifest.get("entrypoint_format") not in (
                "javascript-source",
                "hermes-bytecode",
            ):
                raise BundlePackageError("OTA package entrypoint format is invalid")

            entrypoint_bytes = archive.read(entrypoint)
            if hashlib.sha256(entrypoint_bytes).hexdigest() != internal_manifest.get(
                "entrypoint_sha256"
            ):
                raise BundlePackageError("Bundle entrypoint hash does not match package manifest")

            expected_files = {manifest_name, entrypoint}
            assets = internal_manifest.get("assets", [])
            if not isinstance(assets, list):
                raise BundlePackageError("OTA package assets must be a list")
            seen_assets: set[str] = set()
            for asset in assets:
                if not isinstance(asset, dict):
                    raise BundlePackageError("OTA package asset metadata is invalid")
                asset_path = asset.get("path")
                if (
                    not isinstance(asset_path, str)
                    or not asset_path.startswith("assets/")
                    or asset_path not in files
                    or asset_path in seen_assets
                    or asset_path.removeprefix("assets/")
                    in {
                        "index.android.bundle",
                        "ota-manifest.json",
                        "release-manifest.json",
                        "release-signature.txt",
                    }
                ):
                    raise BundlePackageError("Package manifest references an invalid asset")
                seen_assets.add(asset_path)
                asset_bytes = archive.read(asset_path)
                if len(asset_bytes) != asset.get("size_bytes"):
                    raise BundlePackageError(f"Asset size does not match package manifest: {asset_path}")
                if hashlib.sha256(asset_bytes).hexdigest() != asset.get("sha256"):
                    raise BundlePackageError(f"Asset hash does not match package manifest: {asset_path}")
                expected_files.add(asset_path)

            if expected_files != set(files):
                raise BundlePackageError("Bundle contains files not declared by its package manifest")
    except BundlePackageError:
        raise
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, AttributeError, TypeError) as exc:
        raise BundlePackageError("Uploaded file is not a valid OTA bundle package") from exc
