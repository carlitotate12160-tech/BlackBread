# BlackBread

BlackBread is an authorized, agentless external red-team orchestration platform. The repository
contains the M0 foundation and an in-progress M1 trust-spine ledger slice described in
\`ADR-FINAL-002.md\`. R0/M1 is not complete or production-eligible.

## Implemented slices

1. Python 3.12 project and blocking quality, security, test, and governance gates.
2. FastAPI liveness and database-aware readiness endpoints.
3. PostgreSQL persistence and Alembic migrations.
4. Encrypted, content-addressed local artifact storage.
5. ARM64-compatible Docker Compose runtime.
6. Tenant-bound, hash-versioned, append-only event ledger with replay verification and tamper tests.

## Local development

Install the project and run its checks:

\`\`\`bash
uv sync --locked --all-groups
make check
\`\`\`

Ledger integration tests require a loopback PostgreSQL database named \`blackbread_test\`:

\`\`\`bash
createdb blackbread_test
export BLACKBREAD_TEST_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/blackbread_test"
uv run pytest tests/ledger
\`\`\`

\`ADR-FINAL-002.md\` is the accepted architecture decision. Planned capabilities remain default-denied
in \`config/capability-registry.json\`, and \`LEDGER-GAP-001\` blocks R0 and every target-facing release
until the remaining trust spine is verified.

Generate an artifact encryption key and start the stack:

\`\`\`bash
export BLACKBREAD_ARTIFACT_KEY="$(python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
docker compose up --build
\`\`\`

The API exposes \`GET /health/live\` for process liveness and \`GET /health/ready\` for database and
migration readiness. The API is available at \`http://localhost:8000\`.
