# Server iOS OTA Support Tracker

This tracker reflects implementation in `react-native-ota-server` as of 2026-11-05. Core iOS server support is implemented alongside Android. “Implemented” does not mean the deployed iOS client flow or PostgreSQL CI job has been exercised.

## Baseline findings

- `ReleaseManifest.platform` and `UpdateCheckRequest.platform` accept strict `android`/`ios` values and publish iOS examples in OpenAPI.
- `OtaRelease` persists platform and existing migrations already include platform in lane version uniqueness and the one-active-release index.
- Package build/validation accepts a platform and enforces the selected entrypoint, Hermes bytecode format/header, bounded decompression, asset declarations, and hashes.
- `tools/build_ios_bundle.py` builds `main.jsbundle` with the host app's Metro/Hermes toolchain.
- `tools/ota_signing.py` has `--platform android|ios`, with Android retained as its default.
- Release selection and publication enforce platform lane consistency; model/migrations already included platform in release uniqueness.
- Tests cover iOS package build/validation, signing, publish/check/download isolation, cross-platform active versions, admin rollback/rollout/disable isolation, and OpenAPI platform enums.
- README, `OTA_UPDATE_GUIDE.md`, and `TOOLS_GUIDE.md` now describe iOS artifact generation and publishing.

## Work tracker

| ID | Work item | Status | Evidence / next step |
|---|---|---|---|
| SRV-IOS-01 | Allow strict iOS platform value in signed manifest schema | Implemented | Strict Pydantic platform enum and OpenAPI example. |
| SRV-IOS-02 | Allow strict iOS platform value in update-check request | Implemented | Strict platform enum; unknown platform returns 422. |
| SRV-IOS-03 | Confirm database lane constraints include platform | Implemented and workflow-tested | Existing model/migrations include platform; cross-platform same-version publish and same-lane duplicate rejection covered. |
| SRV-IOS-04 | Generalize deterministic package builder to Android/iOS entrypoints | Implemented and tested | Android `index.android.bundle`, iOS `main.jsbundle`; deterministic ZIP/shared manifest. |
| SRV-IOS-05 | Generalize package validator by platform | Implemented and tested | Platform match, Hermes format/header, path/type/entry/expansion limits, streamed hashes/sizes. |
| SRV-IOS-06 | Add deterministic iOS Hermes bundle builder | Implemented; real-app artifact verified | `tools/build_ios_bundle.py`; successfully built an iOS ZIP from the local React Native client example and validated it. |
| SRV-IOS-07 | Add platform selection to signing CLI | Implemented and tested | `--platform ios`; Android remains default; an iOS manifest was signed and verified by test. |
| SRV-IOS-08 | Validate platform-aware signed package during API publish | Implemented and tested | Publish route passes manifest platform to package validator; signed source-format package rejected and temporary artifact cleaned. |
| SRV-IOS-09 | Test iOS publish/check/download happy path | Implemented and tested | Workflow fixture publishes signed iOS package, gets iOS update response, and downloads matching ZIP bytes. |
| SRV-IOS-10 | Test iOS/Android release isolation | Implemented and tested | Same app/runtime/channel/version can coexist across platforms; each check receives its own platform artifact. |
| SRV-IOS-11 | Test iOS package negative cases | Implemented and tested | Wrong platform, source format, invalid Hermes header, traversal, symlink, duplicate/undeclared entries, and asset hash/size errors. |
| SRV-IOS-12 | Test cross-platform rollout, disable, and rollback behavior | Implemented and tested | iOS rollout/rollback/disable changes leave Android active release delivery unchanged. |
| SRV-IOS-13 | Test upload/storage failure cleanup and immutable behavior | Partially tested | Signed source package and existing hash failures are rejected; promotion and database commit failure injection still needed. |
| SRV-IOS-14 | Update README and OTA/tools guides for iOS server operations | Implemented | Builder/sign/publish commands, iOS lane fields, package format, restart/client verification boundary documented. |
| SRV-IOS-15 | Confirm deployment key/origin/artifact storage readiness for iOS | Documented; deployment validation pending | Existing settings are platform-neutral; production HTTPS, matching public key, persistent storage/backup must be validated in target deployment. |
| SRV-IOS-16 | Add migration/test workflow coverage to CI | Implemented; CI runner pending | `.github/workflows/server-ci.yml` runs pytest/SQLite migration and PostgreSQL migrations; local SQLite migration passed. |
| SRV-IOS-17 | Execute deployed iOS publish/download/check flow | Partially verified locally | Real iOS artifact built/validated and API workflow tested with signed fixtures; deployed service/public HTTPS flow remains. |

## Status legend

- **Implemented and tested:** code exists and the referenced automated check passes.
- **Partially tested / pending:** some local behavior is covered; the listed failure, CI, or deployment evidence remains outstanding.
- Update statuses only when implementation and the associated validation evidence are available.

## Validation log

| Date | Check | Result / evidence |
|---|---|---|
| 2026-11-05 | Implementation inspection | iOS schemas, package handling, signer, publish route, workflow tests, build tool, and documentation implemented. |
| 2026-11-05 | Server tests | `PYTHONPATH=. DATABASE_URL=sqlite+pysqlite:///./ci.db OTA_ADMIN_TOKEN=ci-test-admin-token ./.venv/bin/pytest -q` — 30 passed. |
| 2026-11-05 | SQLite migrations | `DATABASE_URL=sqlite+pysqlite:///:memory: OTA_ADMIN_TOKEN=ci-test-token ./.venv/bin/alembic upgrade head` — passed. |
| 2026-11-05 | OpenAPI platform schema | Verified `ReleaseManifest.platform` and `UpdateCheckRequest.platform` enumerate `android` and `ios`. |
| 2026-11-05 | iOS artifact build/package | Built iOS Hermes OTA ZIP from the sibling client example and validated it with the new platform-aware package validator. |
| — | PostgreSQL migration CI job | Configured in workflow; not run locally. |
| — | Deployed iOS publish/download/check | Not verified. |
