#!/usr/bin/env bash
# Rotate the blackbread_migration and blackbread_app login passwords in place, inside the
# database container, for an EXISTING data volume. Passwords baked in at initialization are
# not changed by editing Compose environment, so a supported rotation needs this explicit,
# transactional command. It changes ONLY passwords: no role attributes, grants, memberships,
# recorder state, schema, migration revision, or application data are touched, and it is
# idempotent when rerun with the same credentials. README.md documents how to invoke it.
set -Eeuo pipefail
set +x  # never trace: credentials are passed to psql as :variables, never echoed

: "${POSTGRES_USER:?set POSTGRES_USER}"
: "${POSTGRES_DB:?set POSTGRES_DB}"
: "${POSTGRES_MIGRATION_PASSWORD:?set POSTGRES_MIGRATION_PASSWORD}"
: "${BLACKBREAD_RUNTIME_DB_PASSWORD:?set BLACKBREAD_RUNTIME_DB_PASSWORD}"

# The superuser connects over the container's trusted local socket, so the current password
# is not required to rotate it. Credentials are bound as psql :variables (never interpolated
# into SQL text). The active-session guard and both rotations run in one transaction, so any
# failure -- including a missing role -- rolls back with every stored password unchanged.
psql \
  --set=ON_ERROR_STOP=1 \
  --no-psqlrc \
  --set=migration_password="${POSTGRES_MIGRATION_PASSWORD}" \
  --set=runtime_password="${BLACKBREAD_RUNTIME_DB_PASSWORD}" \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" <<'SQL'
BEGIN;
DO $$
BEGIN
    -- Only client logins block rotation; background workers (e.g. the logical
    -- replication launcher) also run as the bootstrap superuser and must be ignored.
    IF EXISTS (
        SELECT 1 FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
          AND backend_type = 'client backend'
          AND usename IN ('blackbread_migration', 'blackbread_app')
    ) THEN
        RAISE EXCEPTION 'active blackbread_migration/blackbread_app sessions exist; refusing to rotate';
    END IF;
END
$$;
ALTER ROLE blackbread_migration WITH PASSWORD :'migration_password';
ALTER ROLE blackbread_app WITH PASSWORD :'runtime_password';
COMMIT;
SQL
