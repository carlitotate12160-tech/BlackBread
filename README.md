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
before any container starts if either is missing or empty. Passwords are handed to PostgreSQL
verbatim and are never interpolated into a URL string, so any characters are allowed. Generate
unique secrets and never commit them.

Inside the stack, Compose passes the database coordinates to the `api` and `migrate` services as
separate `BLACKBREAD_DB_*` settings (user, password, host, port, database); the application builds
its SQLAlchemy URL from them via `URL.create`, so a password containing `: @ / ? # %` is preserved
exactly. For a non-Compose run, set either `BLACKBREAD_DATABASE_URL` (a non-empty
`postgresql+asyncpg` URL; the test/development alternative) or the five `BLACKBREAD_DB_*`
components — setting both is ambiguous and rejected.

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
with one explicit, bounded command run inside the running database container. It changes only
the `blackbread_migration` and `blackbread_app` passwords -- no role attributes, grants,
memberships, recorder state, schema, migration revision, or data. The command first creates a
local-only maintenance identity (`blackbread_maint`, LOGIN over the trusted container socket with
no stored password, so it can never authenticate over TCP), then takes a cluster-wide maintenance
boundary: it commits `NOLOGIN` on both rotated roles before checking `pg_stat_activity`, so no new
session can be established for either role with any credential — old or new — while the boundary
holds. One advisory lock serializes both reconciliation and restoration: a run that cannot acquire
it exits without touching either role, so a competing run can never restore `LOGIN` inside another
owner's committed boundary. An active `blackbread_migration`/`blackbread_app` client session
refuses the rotation and `LOGIN` is restored inside the same session — still under boundary
ownership — with nothing rotated. The script is a LF shell script; run it on the Linux deployment
target:

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

**Crash recovery.** If the command is interrupted after the boundary commits but before rotation
completes, both rotated roles remain `NOLOGIN`. Re-running the same command completes the rotation
— `blackbread_maint` is not among the rotated roles, so it can always connect over the container
socket. To release the boundary without rotating, run:

```bash
docker compose exec database psql -U blackbread_maint -d blackbread \
  -c "ALTER ROLE blackbread_migration LOGIN; ALTER ROLE blackbread_app LOGIN"
```

The API exposes `GET /health/live` for process liveness and `GET /health/ready` for database and
migration readiness. The API is available at `http://localhost:8000`.
