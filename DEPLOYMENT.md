# Deployment

See [README.md](README.md#production) for the standalone Compose deployment. Keep `.env.production`, TLS material, public verification keys, and all signing private keys out of Git. The API receives public verification keys only; publisher tools should run in a trusted environment with access to the corresponding private key and API admin token.

The production Compose file builds `Dockerfile` from the repository root, applies database migrations on API startup, persists PostgreSQL and release storage, and serves the API behind Nginx. Verify `/healthz/ready` and `/docs` after deployment.
