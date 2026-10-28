import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.services.bundle_package import build_deterministic_package

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def hermes_compiler_path(mobile_app: Path) -> Path:
    if sys.platform == "darwin":
        os_bin = "osx-bin"
    elif sys.platform.startswith("linux"):
        os_bin = "linux64-bin"
    elif sys.platform == "win32":
        os_bin = "win64-bin"
    else:
        raise SystemExit(f"Unsupported Hermes compiler platform: {sys.platform}")
    binary_name = "hermesc.exe" if sys.platform == "win32" else "hermesc"
    return mobile_app / "node_modules/hermes-compiler/hermesc" / os_bin / binary_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a release-mode Android JavaScript bundle and deterministic OTA ZIP."
    )
    parser.add_argument(
        "--app-dir",
        type=Path,
        default=None,
        help="Host React Native app directory (or set OTA_APP_DIR)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "storage/outgoing/ota-android.zip",
        help="Output ZIP path (default: storage/outgoing/ota-android.zip)",
    )
    args = parser.parse_args()
    app_dir_value = args.app_dir or (Path(os.environ["OTA_APP_DIR"]) if os.environ.get("OTA_APP_DIR") else None)
    if app_dir_value is None:
        raise SystemExit("Provide the host React Native app with --app-dir or OTA_APP_DIR.")
    mobile_app = app_dir_value.expanduser().resolve()

    react_native_cli = mobile_app / "node_modules/.bin/react-native"
    if not react_native_cli.is_file():
        raise SystemExit(f"React Native dependencies are missing; run npm ci in {mobile_app} first.")
    hermesc = hermes_compiler_path(mobile_app)
    if not hermesc.is_file():
        raise SystemExit(f"Matching Hermes compiler not found: {hermesc}")

    with tempfile.TemporaryDirectory(prefix="ota-bundle-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        bundle_path = temporary_root / "index.android.bundle"
        assets_dir = temporary_root / "assets"
        # Metro only creates --assets-dest when the JS bundle references assets.
        # Keep the package builder working for apps that currently have none.
        assets_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(react_native_cli),
                "bundle",
                "--platform",
                "android",
                "--dev",
                "false",
                "--reset-cache",
                "--entry-file",
                "index.js",
                "--bundle-output",
                str(bundle_path),
                "--assets-dest",
                str(assets_dir),
                "--minify",
                "true",
            ],
            cwd=mobile_app,
            check=True,
        )

        bytecode_path = temporary_root / "index.android.bundle.hbc"
        subprocess.run(
            [
                str(hermesc),
                "-w",
                "-emit-binary",
                "-max-diagnostic-width=80",
                "-out",
                str(bytecode_path),
                str(bundle_path),
                "-O",
                "-output-source-map",
            ],
            cwd=mobile_app,
            check=True,
        )

        result = build_deterministic_package(
            bytecode_path,
            assets_dir,
            args.output.resolve(),
            bundle_format="hermes-bytecode",
        )

    print(f"Created: {result['output']}")
    print(f"SHA-256: {result['sha256']}")
    print(f"Size: {result['size_bytes']} bytes")
    print(f"Assets: {result['asset_count']}")


if __name__ == "__main__":
    main()
