# BlackBread

BlackBread is an authorized, agentless external red-team orchestration platform. The repository
contains the M0 foundation and an in-progress M1 trust-spine ledger slice described in
`ADR-FINAL-002.md`. `ADR-FINAL-003.md` adds the campaign-intelligence architecture (verified terrain,
coherent multi-view snapshots, bounded investigation). R0/M1 is not complete or production-eligible.

## Implemented slices

1. Python 3.12 project and blocking quality, security, test, and governance gates.
2. FastAPI liveness and database-aware readiness endpoints.
3. PostgreSQL persistence and Alembic migrations.
4. Encrypted, content-addressed local artifact storage.
5. ARM64-compatible Docker Compose runtime.
6. Tenant-bound, hash-versioned event ledger with a non-owner runtime role, anchored replay
   verification, and tamper tests.
7. Frozen, fail-closed M1 event-schema registry with typed authorization and stop-event records.

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

`ADR-FINAL-002.md` is the accepted foundation architecture; `ADR-FINAL-003.md` is the accepted
amendment for campaign intelligence, verified terrain, and bounded investigation. Planned
capabilities remain default-denied in `config/capability-registry.json`. `LEDGER-GAP-001` blocks
R0; `CAMPAIGN-GAP-001` blocks R1. Both gaps block every target-facing release until closure
evidence is complete.

The typed event catalog validates immutable ledger record shapes only. An
`engagement.attested` record does not itself authorize execution: signature verification,
Conductor admission, Policy Kernel enforcement, leases, and the kill switch remain blocked by
`LEDGER-GAP-001` until their runtime paths are implemented and tested.

### Database credentials

There is no repository-known database credential. `POSTGRES_MIGRATION_PASSWORD` and
`BLACKBREAD_RUNTIME_DB_PASSWORD` are required and must be non-empty; Compose fails configuration
before any container starts if either is missing or empty, and `BLACKBREAD_DATABASE_URL` has no
production-code default. Generate unique secrets and never commit them.

**Fresh volume (first start, or a deliberately empty `postgres-data` volume).** The supplied
credentials bootstrap the roles at initialization:

```bash
export POSTGRES_MIGRATION_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export BLACKBREAD_RUNTIME_DB_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export BLACKBREAD_ARTIFACT_KEY="$(python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
docker compose up --build
```

The database initialization script creates `blackbread_app` as a non-owner member of the
`blackbread_runtime` NOLOGIN role. The migration container uses `blackbread_migration`; the API
uses `blackbread_app`, which receives only the table privileges required by the implemented slice.
A constrained lock sentinel permits row locking without business-column UPDATE access, while a
security-definer insert trigger advances an external count/hash anchor so tail truncation is
detectable.

**Existing volume (rotate credentials without reinitializing).** A volume created before this change
still holds the old passwords; editing the environment alone does not rotate them, because
PostgreSQL only reads `POSTGRES_PASSWORD` and the init script at first initialization. Rotate them
with one explicit, transactional command run inside the running database container. It changes only
the `blackbread_migration` and `blackbread_app` passwords -- no role attributes, grants,
memberships, recorder state, schema, migration revision, or data -- and refuses to proceed if an
unexpected `blackbread_migration`/`blackbread_app` client session is active. The script is a LF
shell script; run it on the Linux deployment target:

```bash
export POSTGRES_MIGRATION_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export BLACKBREAD_RUNTIME_DB_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker compose cp deploy/postgres/reconcile-credentials.sh database:/tmp/reconcile-credentials.sh
docker compose exec -T \
  -e POSTGRES_USER=blackbread_migration -e POSTGRES_DB=blackbread \
  -e POSTGRES_MIGRATION_PASSWORD -e BLACKBREAD_RUNTIME_DB_PASSWORD \
  database bash /tmp/reconcile-credentials.sh
# Then restart the app/migration services so they reconnect with the new passwords:
docker compose up -d --build
```

Re-running the command with the same credentials is idempotent. If an active session blocks it, stop
the api/migrate services first, rotate, then bring them back up.

The API exposes `GET /health/live` for process liveness and `GET /health/ready` for database and
migration readiness. The API is available at `http://localhost:8000`.
