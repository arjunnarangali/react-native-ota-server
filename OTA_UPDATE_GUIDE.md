# Step-by-step Android OTA update guide

This repository contains the FastAPI OTA service and release tools. The React Native Android app is a separate project and must already include the OTA client, trust the publisher public key, and use the same app ID, runtime version, and channel as the release.

For descriptions and standalone commands for each `tools/` script, see [TOOLS_GUIDE.md](TOOLS_GUIDE.md).

## How an OTA release works

1. Build the Android JavaScript bundle and assets from the host React Native app.
2. Package the entrypoint as Hermes bytecode in an OTA ZIP.
3. Sign the release manifest using the publisher private key.
4. Upload the ZIP, manifest, and signature to the API.
5. The installed Android app checks for an eligible release, downloads it, verifies it, and activates it according to the client implementation.

OTA updates carry JavaScript and assets; they do not replace native Android code. Changes to native modules, SDK/native configuration, application ID, or the trusted public key require an appropriately rebuilt Android app. Use a runtime version that represents the native runtime compatibility, and keep it identical across the client request, manifest, and release.

## 1. Prepare the host app and release values

From the React Native app directory, install its dependencies if needed:

```sh
cd "/absolute/path/to/your/react-native-app"
npm ci
```

Confirm the app can resolve every package it imports. The bundling script invokes Metro; it does not install or repair React Native dependencies. The script assumes `index.js` is the entry file, Hermes is used, and the app's `node_modules` contains the React Native CLI and matching Hermes compiler.

Record the exact values configured in the app:

| Value | Example | Must match |
| --- | --- | --- |
| Android application ID | `com.example.app` | Manifest and app update-check request |
| Runtime version | `rn-0.88.0-android-v1` | Manifest and app update-check request |
| Channel | `development` | Upload and app update-check request |
| Release version | `7` | Must be greater than the prior release in the same app/runtime/channel |

Use the keypair already trusted by that app. Do not generate a replacement keypair just to publish another update.

## 2. Configure and start the API

From the server repository root, prepare `.env` from `.env.example` if this is a new local setup. Set database credentials, `DATABASE_URL`, `OTA_ADMIN_TOKEN`, API base URL, storage, and `OTA_SIGNING_PUBLIC_KEY_PATH`. Point the public-key setting at the public key corresponding to the signing private key and embedded in the target Android app.

For a relative public-key path, use a path relative to this server repository root, for example:

```env
OTA_SIGNING_PUBLIC_KEY_PATH=.local-keys/development/ota_publisher_public.pem
```

Then start the database, apply migrations, and run the API:

```sh
docker compose up -d db
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload
```

If Uvicorn is already running, stop it with Ctrl+C and restart it after changing `.env`; the reload watcher does not watch `.env` changes. Check API liveness at `http://127.0.0.1:8000/healthz/live` and database readiness at `http://127.0.0.1:8000/healthz/ready`.

## 3. Build the OTA ZIP

Run from the server repository root with the Python virtual environment active. Give `--app-dir` the absolute path to the host React Native app:

```sh
python -m tools.build_android_bundle \
  --app-dir "/absolute/path/to/your/react-native-app" \
  --output storage/outgoing/ota-android.zip
```

The output ZIP contains `index.android.bundle` (Hermes bytecode), `ota-manifest.json`, and any packaged assets. This command builds the OTA artifact, not an APK, and it does not sign or upload it.

## 4. Sign the release manifest

Use the private key paired with the API/app public key. Set the version higher than the current release for the exact app ID, runtime version, and channel.

```sh
NEXT_VERSION=7
python -m tools.ota_signing sign-manifest \
  --bundle storage/outgoing/ota-android.zip \
  --private-key .local-keys/development/ota-publisher-private.pem \
  --app-id com.example.app \
  --runtime-version rn-0.88.0-android-v1 \
  --version "$NEXT_VERSION" \
  --manifest-output "storage/outgoing/development-v1-${NEXT_VERSION}-manifest.json" \
  --signature-output "storage/outgoing/development-v1-${NEXT_VERSION}-signature.txt"
```

Replace the sample app ID/runtime with the target app's exact configuration. `ota_signing` validates the ZIP and creates a signed manifest containing its digest and size. Keep the private key secret; only the public key belongs in the app and API.

## 5. Publish to the API

For local development, `.env` must contain a valid `OTA_API_BASE_URL` (usually `http://127.0.0.1:8000`) and `OTA_ADMIN_TOKEN`. Publish to the channel configured by the test app. A `100%` rollout is useful for a controlled development test:

```sh
python -m tools.publish_release \
  --bundle storage/outgoing/ota-android.zip \
  --manifest "storage/outgoing/development-v1-${NEXT_VERSION}-manifest.json" \
  --signature "storage/outgoing/development-v1-${NEXT_VERSION}-signature.txt" \
  --channel development \
  --rollout 100
```

The upload succeeds only if the API can verify the manifest signature and the bundle hash/size and package structure are valid. A newer successful upload becomes active and archives the previously active release for that app/runtime/channel.

## 6. Verify delivery in the app

Install/run an Android app build that has the matching public key, app ID, runtime version, channel, and API origin. Trigger its OTA check using the client application's supported flow. The server selects only active releases that match the request's platform, app ID, runtime version, and channel; rollout policy also applies. A successful upload alone does not prove that a device has downloaded or activated the update.

The API provides:

- `GET /healthz/ready` to check API and database readiness.
- `GET /api/v1/admin/releases` to inspect releases (admin bearer token required).
- `POST /api/v1/updates/check` for the client update check.
- `GET /api/v1/releases/{release_id}/bundle` for artifact download.

The interactive API docs are at `http://127.0.0.1:8000/docs` for a local server.

## Production release

Production uses `.env.production` for the release tool's API origin and admin token. Keep it private and ensure the production API itself has the matching production public key configured. Production origins must use HTTPS.

The orchestrator builds, signs, selects the next matching release version, and publishes to `production`:

```sh
python -m tools.release_production \
  --env-file .env.production \
  --app-dir "/absolute/path/to/your/react-native-app" \
  --app-id com.example.app \
  --runtime-version rn-0.88.0-android-v1 \
  --rollout 5
```

The default rollout is `5%`; increase it after validating the release. To publish a bundle already built by `build_android_bundle.py`, replace `--app-dir` with `--bundle storage/outgoing/production-ota.zip`. The default production private key is `.local-keys/production/ota-publisher-private.pem`; pass `--private-key` to use another location. For a manual build/sign/upload flow, see [TOOLS_GUIDE.md](TOOLS_GUIDE.md).

## Rollout and rollback

- Use `--rollout 100` for a controlled development channel only when every matching test installation should be eligible.
- For production, start with a small percentage and increase it after monitoring the client behavior.
- The API assigns installations to a stable rollout bucket based on release ID and installation ID.
- To change rollout, use `PATCH /api/v1/admin/releases/{release_id}/rollout` with JSON `{"rollout_percentage": 25}` and an admin bearer token.
- To stop serving a release, use `POST /api/v1/admin/releases/{release_id}/disable`.
- To reactivate a prior release, use `POST /api/v1/admin/releases/{release_id}/rollback`. The API marks it active at 100% and treats it as a rollback for compatible clients.

These admin operations require `Authorization: Bearer <OTA_ADMIN_TOKEN>`.

## Troubleshooting

| Symptom | Meaning / check |
| --- | --- |
| Metro says `Unable to resolve module ...` | The host app import does not resolve to an installed dependency. Check that app's dependency name/install and source imports; bundle generation runs Metro. |
| `Publisher public signing key is unavailable` (503) | The API could not open or parse its configured public key. Check `OTA_SIGNING_PUBLIC_KEY_PATH`, resolve relative paths from the server repository root, ensure the file is readable PEM, and restart the API after changing `.env`. |
| `Release manifest signature is invalid` (400) | The signing private key does not match the API's public key, or the manifest/signature pair is not from the same signing operation. |
| `Bundle hash does not match signed manifest` (400) | The ZIP changed after signing, or the manifest was created for another bundle. Build/sign again as a pair. |
| Version conflict (409) | The version is not greater than the latest release for that app ID, runtime version, and channel. |
| The app reports no update | Check app ID, runtime version, channel, current version, rollout eligibility, and that the release is active. |
| `[Errno 48] Address already in use` | Port 8000 is already occupied. Stop the existing Uvicorn process or start this instance on another port. |
