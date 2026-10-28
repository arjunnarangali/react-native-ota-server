# Python tools reference

This guide explains when to use each script in `tools/` and gives runnable commands. Run commands from the **server repository root** with its Python virtual environment active. Use `python -m tools.<module>` so the repository's `app` package imports correctly.

For the end-to-end release workflow, see [OTA_UPDATE_GUIDE.md](OTA_UPDATE_GUIDE.md).

## One-time Python setup

This project requires Python 3.12 or newer.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Tool summary

| Script | Use it when | Does not do |
| --- | --- | --- |
| `build_android_bundle.py` | Build and package an Android Hermes OTA bundle from the host React Native app. | Sign or upload the bundle; build an APK. |
| `ota_signing.py` | Generate a P-256 signing keypair once, or sign a bundle's release manifest. | Upload a release. |
| `publish_release.py` | Upload an already-built and signed release to an API, commonly a local or development server. | Build or sign the release. |
| `release_production.py` | Run the complete production sequence: choose version, build or reuse bundle, sign, upload. | Build the native Android APK. |
| `publish_production_release.py` | Upload an already-built and signed production release using `.env.production`. | Build or sign the release. |
| `__init__.py` | Marks `tools/` as an importable Python package so `python -m tools.<module>` works. | Provide a standalone command. |

## `build_android_bundle.py`

Builds a Metro Android release bundle, compiles it to Hermes bytecode using the host app's Hermes compiler, and packages the entrypoint and Metro assets into a deterministic ZIP.

The host React Native app must be provided explicitly. It must have its Node dependencies installed, a local `node_modules/.bin/react-native` CLI, and `node_modules/hermes-compiler` for the host operating system. The script uses `index.js` as the Metro entry file and targets Android/Hermes.

```sh
python -m tools.build_android_bundle \
  --app-dir "/absolute/path/to/your/react-native-app" \
  --output storage/outgoing/ota-android.zip
```

`--output` is optional; the default is `storage/outgoing/ota-android.zip`. `OTA_APP_DIR` can also provide the app path if it is exported in the process environment. This script does not load `.env` to find `OTA_APP_DIR`.

If Metro reports that it cannot resolve a JavaScript package, the failure is in the host app's dependency/install/import setup; the Python script is reporting Metro's non-zero exit.

## `ota_signing.py`

### Generate a keypair once

Use this only when creating a new publisher identity. Do not run it to repair a path issue or replace a key already trusted by installed apps. The Android app and API must use the corresponding public key, and the private key must remain private.

```sh
python -m tools.ota_signing generate-keys \
  --private-key .local-keys/development/ota-publisher-private.pem \
  --public-key .local-keys/development/ota-publisher-public.pem
```

The private key is created with owner-only permissions. The public key should be configured in the API (`OTA_SIGNING_PUBLIC_KEY_PATH`) and embedded in the compatible Android app. Keep the private key out of Git and out of the app.

### Sign an OTA package

Signing validates that the ZIP is a valid OTA package containing Hermes bytecode, calculates its SHA-256 and size, builds a manifest, and signs the canonical manifest with P-256 ECDSA.

```sh
NEXT_VERSION=7
python -m tools.ota_signing sign-manifest \
  --bundle storage/outgoing/ota-android.zip \
  --private-key .local-keys/development/ota-publisher-private.pem \
  --app-id com.example.app \
  --runtime-version rn-0.88.0-android-v1 \
  --version "$NEXT_VERSION" \
  --manifest-output "storage/outgoing/development-${NEXT_VERSION}-manifest.json" \
  --signature-output "storage/outgoing/development-${NEXT_VERSION}-signature.txt"
```

Replace the example app ID and runtime version with the exact values used by the installed app. The release version must be greater than the existing version for the same app ID, runtime version, and channel. Signing alone does not check the server's release history; the API enforces version ordering during upload.

## `publish_release.py`

Uploads a prepared ZIP, manifest, and signature to `POST /api/v1/admin/releases`. It gets `OTA_API_BASE_URL` and `OTA_ADMIN_TOKEN` from the server repository's `.env` via application settings. `DATABASE_URL` must also be present because settings require it, although this publishing script does not connect to the database.

```sh
python -m tools.publish_release \
  --bundle storage/outgoing/ota-android.zip \
  --manifest storage/outgoing/development-7-manifest.json \
  --signature storage/outgoing/development-7-signature.txt \
  --channel development \
  --rollout 100
```

Options: `--channel` defaults to `production`; `--rollout` defaults to `100` and accepts `0` through `100`. The API verifies the signature, artifact size/hash and ZIP contents, then activates the release. Publishing a newer release for that app/runtime/channel archives the previously active release.

## `release_production.py`

Orchestrates a production release. It reads credentials and API origin from `.env.production`, checks release history, chooses the next version if one is not supplied, then builds (or reuses), signs, and uploads a production release.

The production env file must contain a real `OTA_ADMIN_TOKEN` and `OTA_API_BASE_URL` (or `OTA_PUBLIC_BASE_URL`). Non-local production origins must use HTTPS. The target server must already have the matching production public key configured.

Build the bundle from the host app:

```sh
python -m tools.release_production \
  --env-file .env.production \
  --app-dir "/absolute/path/to/your/react-native-app" \
  --app-id com.example.app \
  --runtime-version rn-0.88.0-android-v1 \
  --rollout 5
```

By default the production app ID is `com.ota`, runtime version is `rn-0.88.0-android-v4`, channel is `production`, bundle output is `storage/outgoing/production-ota.zip`, and rollout is `5%`. Supply the values matching the production Android app; do not rely on defaults if your app uses different values. By default the private key is `.local-keys/production/ota-publisher-private.pem`; `--private-key` or `PRODUCTION_SIGNING_KEY` can select another path.

To reuse an already-built bundle, pass `--bundle` instead of `--app-dir`:

```sh
python -m tools.release_production \
  --env-file .env.production \
  --bundle storage/outgoing/production-ota.zip \
  --private-key .local-keys/production/ota-publisher-private.pem \
  --app-id com.example.app \
  --runtime-version rn-0.88.0-android-v1 \
  --rollout 5
```

Without `--version`, the tool selects the latest matching production version plus one. `--version` can set it explicitly, or an exported `NEXT_VERSION` can supply the default version (for example, `export NEXT_VERSION=8`). An explicit version must be higher than the current one.

## `publish_production_release.py`

Uploads an already-built and signed bundle to the production channel using credentials from `.env.production`. It is normally called by `release_production.py`; use it directly when all three artifacts already exist.

```sh
python -m tools.publish_production_release \
  --env-file .env.production \
  --bundle storage/outgoing/production-ota.zip \
  --manifest storage/outgoing/production-7-manifest.json \
  --signature storage/outgoing/production-7-signature.txt \
  --rollout 5
```

It calls the same upload implementation as `publish_release.py` and sets channel to `production`. Its rollout default is `5`.

## Common failures

- **Metro cannot resolve a module:** fix the host app's JavaScript dependency/import mismatch and install its dependencies before building the bundle.
- **`Publisher public signing key is unavailable` (503):** the API cannot open or parse the public key at its configured `OTA_SIGNING_PUBLIC_KEY_PATH`. Relative paths resolve from the server repository root. Restart the API after changing `.env`.
- **`Release manifest signature is invalid` (400):** the private key used to sign does not match the public key configured by the API, or the manifest/signature pair is not the same release.
- **Version conflict (409):** use a higher version for the same app ID, runtime version, and channel.
- **Address already in use:** Uvicorn's default port is `8000`; stop the existing server or choose a different port.
