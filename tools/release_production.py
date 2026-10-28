import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPOSITORY_ROOT
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.production"
DEFAULT_BUNDLE = SERVER_ROOT / "storage/outgoing/production-ota.zip"
DEFAULT_PRIVATE_KEY = SERVER_ROOT / ".local-keys/production/ota-publisher-private.pem"
DEFAULT_APP_ID = "com.ota"
DEFAULT_RUNTIME_VERSION = "rn-0.88.0-android-v4"
CHANNEL = "production"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build (or reuse), sign, and upload a production OTA release."
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--bundle", type=Path, help="Reuse this existing bundle instead of building one")
    parser.add_argument("--app-dir", type=Path, help="Host React Native app directory for bundle building")
    parser.add_argument("--private-key", type=Path, help="Production OTA signing key; defaults to PRODUCTION_SIGNING_KEY or the local production key")
    parser.add_argument("--app-id", default=DEFAULT_APP_ID)
    parser.add_argument("--runtime-version", default=DEFAULT_RUNTIME_VERSION)
    parser.add_argument(
        "--version",
        type=int,
        default=os.environ.get("NEXT_VERSION"),
        help="Release version; uses NEXT_VERSION if set, otherwise latest production version + 1",
    )
    parser.add_argument("--rollout", type=int, default=5, choices=range(0, 101))
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded.resolve() if expanded.is_absolute() else (SERVER_ROOT / expanded).resolve()


def load_production_settings(env_file: Path) -> tuple[str, str]:
    if not env_file.is_file():
        raise SystemExit(f"Production environment file not found: {env_file}")
    values = dotenv_values(env_file)
    token = (values.get("OTA_ADMIN_TOKEN") or "").strip()
    api_base_url = (values.get("OTA_API_BASE_URL") or values.get("OTA_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not token or token.lower().startswith("replace-"):
        raise SystemExit(f"Set the real production OTA_ADMIN_TOKEN in {env_file}")
    if not api_base_url:
        raise SystemExit(f"Set OTA_API_BASE_URL or OTA_PUBLIC_BASE_URL in {env_file}")

    parsed_url = urlsplit(api_base_url)
    local_http = parsed_url.scheme == "http" and parsed_url.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        (parsed_url.scheme != "https" and not local_http)
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or (parsed_url.path not in ("", "/") and not local_http)
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise SystemExit("Production API URL must be an HTTPS origin")
    return api_base_url, token


def latest_production_version(api_base_url: str, token: str, app_id: str, runtime_version: str) -> int:
    try:
        response = httpx.get(
            f"{api_base_url}/api/v1/admin/releases",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        releases = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SystemExit(f"Could not read production release history: {exc}") from exc

    if not isinstance(releases, list):
        raise SystemExit("Production release history returned an unexpected response")

    versions = []
    for release in releases:
        manifest = release.get("manifest", {}) if isinstance(release, dict) else {}
        if (
            manifest.get("app_id") == app_id
            and manifest.get("runtime_version") == runtime_version
            and release.get("channel") == CHANNEL
        ):
            try:
                versions.append(int(manifest["version"]))
            except (KeyError, TypeError, ValueError):
                continue
    return max(versions, default=0)


def run_tool(*arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=SERVER_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    args = parse_args()
    env_file = args.env_file.expanduser()
    if not env_file.is_absolute():
        env_file = REPOSITORY_ROOT / env_file
    env_file = env_file.resolve()
    api_base_url, token = load_production_settings(env_file)

    if args.version is None:
        version = latest_production_version(api_base_url, token, args.app_id, args.runtime_version) + 1
        print(f"Selected next production version: {version}", flush=True)
    else:
        version = args.version
        if version < 1:
            raise SystemExit("--version must be a positive integer")
        latest_version = latest_production_version(api_base_url, token, args.app_id, args.runtime_version)
        if version <= latest_version:
            raise SystemExit(
                f"Version {version} is not newer than the latest production version {latest_version}"
            )

    private_key = args.private_key or Path(os.environ.get("PRODUCTION_SIGNING_KEY", str(DEFAULT_PRIVATE_KEY)))
    private_key = resolve_path(private_key)
    if not private_key.is_file():
        raise SystemExit(f"Production OTA signing key not found: {private_key}")

    bundle = resolve_path(args.bundle) if args.bundle else DEFAULT_BUNDLE
    if args.bundle:
        if not bundle.is_file():
            raise SystemExit(f"Bundle file not found: {bundle}")
        print(f"Using existing bundle: {bundle}", flush=True)
    else:
        print("Building production OTA bundle...", flush=True)
        app_dir = args.app_dir or (Path(os.environ["OTA_APP_DIR"]) if os.environ.get("OTA_APP_DIR") else None)
        if app_dir is None:
            raise SystemExit("Provide --app-dir or OTA_APP_DIR to build a host app bundle, or pass --bundle.")
        run_tool("-m", "tools.build_android_bundle", "--app-dir", str(app_dir), "--output", str(bundle))

    manifest = SERVER_ROOT / f"storage/outgoing/production-{version}-manifest.json"
    signature = SERVER_ROOT / f"storage/outgoing/production-{version}-signature.txt"
    print(f"Signing production bundle as version {version}...", flush=True)
    run_tool(
        "-m",
        "tools.ota_signing",
        "sign-manifest",
        "--bundle",
        str(bundle),
        "--private-key",
        str(private_key),
        "--app-id",
        args.app_id,
        "--runtime-version",
        args.runtime_version,
        "--version",
        str(version),
        "--manifest-output",
        str(manifest),
        "--signature-output",
        str(signature),
    )

    print(f"Uploading production version {version} at {args.rollout}% rollout...", flush=True)
    run_tool(
        "-m",
        "tools.publish_production_release",
        "--env-file",
        str(env_file),
        "--bundle",
        str(bundle),
        "--manifest",
        str(manifest),
        "--signature",
        str(signature),
        "--rollout",
        str(args.rollout),
    )


if __name__ == "__main__":
    main()
