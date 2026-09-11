#!/usr/bin/env bash
# Rotate the blackbread_migration and blackbread_app login passwords in place, inside the
# database container, for an EXISTING data volume. Passwords baked in at initialization are
# not changed by editing Compose environment, so a supported rotation needs this explicit,
# transactional command. It changes ONLY passwords plus a temporary LOGIN suspension: no
# role attributes, grants, memberships, recorder state, schema, migration revision, or
# application data are touched, and it is idempotent when rerun with the same credentials.
# README.md documents how to invoke it and how to recover an interrupted run.
#
# Maintenance boundary (no check-to-ALTER race):
#   0. A local-only maintenance identity (blackbread_maint) is ensured first: LOGIN over
#      the trusted container socket but with no stored password, so it has no usable TCP
#      credential and is never among the rotated roles — it survives an interrupted run.
#   1. One PostgreSQL advisory lock serializes all reconciliation runs.
#   2. NOLOGIN for both rotated roles is committed BEFORE the session check, so from that
#      instant no new session can be established for either role with any credential.
#   3. pg_stat_activity is checked cluster-wide for both roles; an active client session
#      refuses the run and the boundary is released (LOGIN restored) with nothing rotated.
#   4. Both passwords rotate and LOGIN is restored inside one transaction: all or nothing.
# If the script is interrupted between steps 2 and 4, both roles stay NOLOGIN; re-running
# this script completes the rotation because the maintenance identity remains LOGIN.
set -Eeuo pipefail
set +x  # never trace: credentials reach psql only via the stdin \set stream below

: "${POSTGRES_USER:?set POSTGRES_USER}"
: "${POSTGRES_DB:?set POSTGRES_DB}"
: "${POSTGRES_MIGRATION_PASSWORD:?set POSTGRES_MIGRATION_PASSWORD}"
: "${BLACKBREAD_RUNTIME_DB_PASSWORD:?set BLACKBREAD_RUNTIME_DB_PASSWORD}"

MAINT_ROLE=blackbread_maint
# Advisory-lock key 727274 (in the SQL below) serializes reconciliation runs; it is a
# stable constant, never derived from secrets, and mirrors ADVISORY_LOCK_KEY in the
# deployment test suite.

_psql() {
    psql --no-psqlrc -v ON_ERROR_STOP=1 -tAq "$@"
}

# Ensure the maintenance identity exists. First run on a volume uses the bootstrap
# superuser while it is still LOGIN; later runs (including after an interrupted run)
# find the identity already present. SUPERUSER is required to alter the bootstrap
# superuser role; the NULL password keeps it off the network permanently.
if ! _psql -U "$MAINT_ROLE" -d "$POSTGRES_DB" -c 'SELECT 1' >/dev/null 2>&1; then
    _psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "CREATE ROLE $MAINT_ROLE SUPERUSER LOGIN" >/dev/null
fi

# Restore LOGIN for both rotated roles on a controlled failure: the committed
# boundary is released and no password is left half-rotated. Each statement runs
# as its own implicit transaction so one missing role cannot roll back the
# other's restore. Harmless when the rotation already committed.
restore_login() {
    _psql -U "$MAINT_ROLE" -d "$POSTGRES_DB" -c \
        "ALTER ROLE blackbread_migration LOGIN" >/dev/null 2>&1 || true
    _psql -U "$MAINT_ROLE" -d "$POSTGRES_DB" -c \
        "ALTER ROLE blackbread_app LOGIN" >/dev/null 2>&1 || true
}

# psql \set quoting: wrap in single quotes with '' escaping; values then travel on
# stdin (never argv) and are bound into SQL literals via :'name'.
_psql_quote() {
    printf "'%s'" "${1//\'/\'\'}"
}

if ! {
    printf '\\set migration_password %s\n' "$(_psql_quote "$POSTGRES_MIGRATION_PASSWORD")"
    printf '\\set runtime_password %s\n' "$(_psql_quote "$BLACKBREAD_RUNTIME_DB_PASSWORD")"
    cat <<'SQL'
DO $$
BEGIN
    IF NOT pg_try_advisory_lock(727274) THEN
        RAISE EXCEPTION 'another credential reconciliation holds the advisory lock';
    END IF;
END
$$;
-- Boundary: once committed, NOLOGIN blocks every new session for both rotated
-- roles regardless of credential — the check-to-ALTER window cannot produce one.
ALTER ROLE blackbread_migration NOLOGIN;
ALTER ROLE blackbread_app NOLOGIN;
DO $$
BEGIN
    -- pg_stat_activity is cluster-wide (all databases). Only client logins block
    -- rotation; background workers run as the bootstrap superuser and are ignored.
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
-- Atomic rotation: both passwords and the LOGIN restore commit or roll back together.
BEGIN;
ALTER ROLE blackbread_migration WITH LOGIN PASSWORD :'migration_password';
ALTER ROLE blackbread_app WITH LOGIN PASSWORD :'runtime_password';
COMMIT;
SQL
} | _psql -U "$MAINT_ROLE" -d "$POSTGRES_DB" -f -; then
    restore_login
    echo "credential reconciliation refused; LOGIN restored, no password changed" >&2
    exit 1
fi

echo "database credentials rotated"
