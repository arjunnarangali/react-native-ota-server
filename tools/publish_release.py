import argparse
from pathlib import Path

import httpx

from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a signed OTA bundle to the FastAPI service.")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--channel", default="production")
    parser.add_argument("--rollout", type=int, default=100, choices=range(0, 101))
    args = parser.parse_args()

    if not settings.ota_admin_token:
        raise SystemExit("Set OTA_ADMIN_TOKEN in the repository .env before publishing")
    if not args.bundle.is_file() or not args.manifest.is_file() or not args.signature.is_file():
        raise SystemExit("Bundle, manifest, and signature files must all exist")

    endpoint = f"{settings.ota_api_base_url.rstrip('/')}/api/v1/admin/releases"
    with args.bundle.open("rb") as bundle_file:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.ota_admin_token}"},
            data={
                "manifest": args.manifest.read_text(encoding="utf-8"),
                "signature": args.signature.read_text(encoding="ascii").strip(),
                "channel": args.channel,
                "rollout_percentage": str(args.rollout),
            },
            files={"bundle": (args.bundle.name, bundle_file, "application/zip")},
            timeout=120,
        )

    if response.is_error:
        raise SystemExit(f"Publish failed ({response.status_code}): {response.text}")

    release = response.json()
    print(f"Published release {release['release_id']} to {release['channel']}")
    print(f"State: {release['state']}; rollout: {release['rollout_percentage']}%")


if __name__ == "__main__":
    main()
