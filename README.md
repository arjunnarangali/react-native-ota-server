# React Native OTA Server

Standalone FastAPI service for signed Android OTA releases. The service stores release artifacts, selects compatible releases by app/runtime/channel, applies rollout policy, and supports operator rollback. The contract is exposed at `/openapi.json` and `/docs`.

Operational guides: [Python tools reference](TOOLS_GUIDE.md) and [step-by-step Android OTA update guide](OTA_UPDATE_GUIDE.md).

## Requirements

- Python 3.12+
- Docker Compose for PostgreSQL and production deployment
- A host app's Android public verification key; never place a signing private key in this repository or on the API host

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

The signing/publishing tools accept a caller-provided bundle and signing key paths. Use `tools.build_android_bundle --app-dir /path/to/host/app` (or `OTA_APP_DIR`) to build a bundle from a host application's installed React Native toolchain; this repository does not contain an app. `tools.release_production --bundle ... --private-key ...` can publish a prepared bundle. Protect publisher private keys and API credentials outside Git.

## Client integration and protocol

Install and integrate the Android client from the separate [`react-native-ota-client`](https://github.com/arjunnarangali/react-native-ota-client) repository. The client sends platform, app ID, runtime version, channel, current OTA version, stable installation ID, and optional failed release ID to the update-check endpoint. The response provides a signed manifest, signature, channel, rollout percentage, action (`update` or `rollback`), and bundle URL. The server OpenAPI schema is authoritative; manifests must match the app/runtime and the client verifies signatures and artifact hashes before activation.

## Tests

```sh
python -m pip install -r requirements.txt
pytest
```
