# Server operator guide

This repository root is the working directory for Python commands (`pytest`, `alembic`, `uvicorn`, and `python -m tools.*`). Configure database connectivity, API credentials, public-key location, storage, and the public API origin through environment variables or the ignored root `.env` file. See [README.md](README.md) for local setup, production deployment, client integration, and the API contract.

For a service release built from a host application, provide that app's absolute path with `--app-dir`; no `mobile/OTA` path is assumed. For prepared artifacts, invoke the release tool with `--bundle` and an explicit private key path.
