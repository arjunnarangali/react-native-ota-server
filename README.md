# React Native OTA Server

Standalone FastAPI service for signed Android and iOS OTA releases. The service stores release artifacts, selects compatible releases by platform/app/runtime/channel, applies rollout policy, and supports operator rollback. The contract is exposed at `/openapi.json` and `/docs`.

Operational guides: [Python tools reference](TOOLS_GUIDE.md) and [step-by-step OTA update guide](OTA_UPDATE_GUIDE.md).

## Requirements

- Python 3.12+
- Docker Compose for PostgreSQL and production deployment
- The public verification key for the release environment; never place a signing private key in this repository or on the API host

## Local development

```sh
cp .env.example .env
# Set both database passwords and OTA_ADMIN_TOKEN in .env.
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; check `/healthz/ready` and `/docs`. Set `OTA_SIGNING_PUBLIC_KEY_PATH` to the host app's public PEM. `OTA_STORAGE_DIR` defaults to `storage/releases`. Run `pytest` from this repository root.

## Production

Copy `.env.production.example` to `.env.production`, replace all placeholders, put the environment's **public** PEM at the configured `OTA_PUBLIC_KEY_FILE`, and review the configuration before starting:

```sh
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml up -d --build
```

The API image is built from this repository root. Compose applies Alembic migrations before starting the service. Persistent PostgreSQL and artifact volumes are managed by Compose. `deploy-production.sh` supports deployment from a clean Git checkout.

## Publishing

The signing/publishing tools accept a caller-provided bundle and signing key paths. Use `tools.build_android_bundle --app-dir /path/to/host/app` or `tools.build_ios_bundle --app-dir /path/to/host/app` (or `OTA_APP_DIR`) to build from a host application's installed React Native/Hermes toolchain; this repository does not contain a mobile app. Sign with `tools.ota_signing sign-manifest`; the `--platform` option defaults to Android and accepts `ios`. `tools.release_production --bundle ... --private-key ...` publishes prepared Android bundles to production; for iOS production releases use `python -m tools.publish_production_release` with a production-signed manifest. Protect publisher private keys and API credentials outside Git.

## Client integration and protocol

Install and integrate the Android/iOS client from the separate [`react-native-ota-client`](https://github.com/arjunnarangali/react-native-ota-client) repository. The client sends platform, app ID, runtime version, channel, current OTA version, stable installation ID, and optional failed release ID to the update-check endpoint. Releases are isolated by platform, app ID, runtime, and channel. The response provides a signed manifest, signature, channel, rollout percentage, action (`update` or `rollback`), and bundle URL. iOS ZIPs use `main.jsbundle`; Android ZIPs use `index.android.bundle`. The server OpenAPI schema is authoritative; clients verify signatures and artifact/file hashes before activation.

## Tests

```sh
python -m pip install -r requirements.txt
pytest
```
