# BlackBread

BlackBread is an authorized, agentless external red-team orchestration platform. The repository
contains the M0 foundation and an in-progress M1 trust-spine ledger slice described in
`ADR-FINAL-002.md`. R0/M1 is not complete or production-eligible.

## Implemented slices

1. Python 3.12 project and blocking quality, security, test, and governance gates.
2. FastAPI liveness and database-aware readiness endpoints.
3. PostgreSQL persistence and Alembic migrations.
4. Encrypted, content-addressed local artifact storage.
5. ARM64-compatible Docker Compose runtime.
6. Tenant-bound, hash-versioned event ledger with a non-owner runtime role, replay verification,
   and tamper tests.

## Local development

Install the project and run its checks:

```bash
uv sync --locked --all-groups
make check
```

Ledger integration tests require a loopback PostgreSQL database named `blackbread_test`. The
fixture uses the migration owner only for schema/recovery setup and creates a separate non-owner
runtime login for application tests:

```bash
createdb blackbread_test
export BLACKBREAD_TEST_MIGRATION_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/blackbread_test"
export BLACKBREAD_TEST_DATABASE_URL="postgresql+asyncpg://blackbread_test_runtime:blackbread_test_runtime@127.0.0.1:5432/blackbread_test"
export BLACKBREAD_TEST_RUNTIME_PASSWORD="blackbread_test_runtime"
uv run pytest tests/ledger
```

`ADR-FINAL-002.md` is the accepted architecture decision. Planned capabilities remain default-denied
in `config/capability-registry.json`, and `LEDGER-GAP-001` blocks R0 and every target-facing release
until the remaining trust spine is verified.

Generate separate migration/runtime database credentials and an artifact encryption key before
starting the stack:

```bash
export POSTGRES_MIGRATION_PASSWORD="replace-with-migration-secret"
export BLACKBREAD_RUNTIME_DB_PASSWORD="replace-with-runtime-secret"
export BLACKBREAD_ARTIFACT_KEY="$(python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
docker compose up --build
```

The database initialization script creates `blackbread_app` as a non-owner member of the
`blackbread_runtime` NOLOGIN role. The migration container uses `blackbread_migration`; the API
uses `blackbread_app`, which receives only the table privileges required by the implemented slice.
Existing development volumes created before this split must be reinitialized deliberately.

The API exposes `GET /health/live` for process liveness and `GET /health/ready` for database and
migration readiness. The API is available at `http://localhost:8000`.
