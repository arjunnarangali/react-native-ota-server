import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPOSITORY_ROOT
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.production"
UNUSED_DATABASE_URL = "postgresql+psycopg://unused:unused@127.0.0.1:5432/unused"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a signed OTA bundle using API credentials from .env.production."
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--rollout", type=int, default=5, choices=range(0, 101))
    return parser.parse_args()


def resolve_from_repository(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded.resolve() if expanded.is_absolute() else (REPOSITORY_ROOT / expanded).resolve()


def main() -> None:
    args = parse_args()
    env_file = resolve_from_repository(args.env_file)
    if not env_file.is_file():
        raise SystemExit(f"Production environment file not found: {env_file}")

    publisher_settings = dotenv_values(env_file)
    api_base_url = (
        publisher_settings.get("OTA_API_BASE_URL")
        or publisher_settings.get("OTA_PUBLIC_BASE_URL")
        or ""
    ).strip().rstrip("/")
    admin_token = (publisher_settings.get("OTA_ADMIN_TOKEN") or "").strip()
    if not api_base_url:
        raise SystemExit(f"OTA_API_BASE_URL or OTA_PUBLIC_BASE_URL is missing from {env_file}")
    if not admin_token:
        raise SystemExit(f"OTA_ADMIN_TOKEN is missing from {env_file}")

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
        raise SystemExit("OTA_API_BASE_URL must be an HTTPS origin (HTTP is allowed only for localhost tests)")

    artifacts = {
        "bundle": args.bundle,
        "manifest": args.manifest,
        "signature": args.signature,
    }
    resolved_artifacts: dict[str, Path] = {}
    for name, path in artifacts.items():
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise SystemExit(f"{name.capitalize()} file not found: {resolved}")
        resolved_artifacts[name] = resolved

    child_environment = os.environ.copy()
    child_environment.update(
        {
            "OTA_API_BASE_URL": api_base_url,
            "OTA_ADMIN_TOKEN": admin_token,
            # publish_release imports Settings, which requires this value, but does not connect to a DB.
            "DATABASE_URL": UNUSED_DATABASE_URL,
        }
    )
    command = [
        sys.executable,
        "-m",
        "tools.publish_release",
        "--bundle",
        str(resolved_artifacts["bundle"]),
        "--manifest",
        str(resolved_artifacts["manifest"]),
        "--signature",
        str(resolved_artifacts["signature"]),
        "--channel",
        "production",
        "--rollout",
        str(args.rollout),
    ]
    result = subprocess.run(command, cwd=SERVER_ROOT, env=child_environment, check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
