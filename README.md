# BlackBread

BlackBread is an authorized, agentless external red-team orchestration platform. The repository
currently implements the M0 foundation described in `ADR-FINAL-002.md`.

## M0 slices

1. Python 3.12 project and quality gates.
2. FastAPI liveness and database-aware readiness endpoints.
3. PostgreSQL persistence and Alembic migration bootstrap.
4. Encrypted, content-addressed local artifact storage.
5. ARM64-compatible Docker Compose runtime.

## Local development

Install the project and run its checks:

```bash
uv sync --locked --all-groups
make check
```

`ADR-FINAL-002.md` is the accepted architecture decision; the live implementation remains M0 only.
Planned capabilities are default-denied in `config/capability-registry.json`. See `GAP-REGISTER.md`
before claiming a milestone or release complete.

Generate an artifact encryption key and start the stack:

```bash
export BLACKBREAD_ARTIFACT_KEY="$(python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
docker compose up --build
```

The API exposes `GET /health/live` for process liveness and `GET /health/ready` for database and
migration readiness. The API is available at `http://localhost:8000`.
