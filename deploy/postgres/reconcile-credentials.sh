#!/usr/bin/env bash
# Rotate the blackbread_migration and blackbread_app login passwords in place, inside the
# database container, for an EXISTING data volume. Passwords baked in at initialization are
# not changed by editing Compose environment, so a supported rotation needs this explicit,
# transactional command. It changes ONLY passwords plus a temporary LOGIN suspension: no
# role attributes, grants, memberships, recorder state, schema, migration revision, or
# application data are touched, and it is idempotent when rerun with the same credentials.
# README.md documents how to invoke it and how to recover an interrupted run.
#
# Maintenance boundary (no check-to-ALTER race, no competing-run restore race):
#   0. A local-only maintenance identity (blackbread_maint) is ensured first: LOGIN over
#      the trusted container socket but with no stored password, so it has no usable TCP
#      credential and is never among the rotated roles — it survives an interrupted run.
#   1. One PostgreSQL advisory lock serializes reconciliation AND restoration. A run that
#      cannot acquire it exits WITHOUT mutating either rotated role.
#   2. NOLOGIN for both rotated roles is committed BEFORE the session check, so from that
#      instant no new session can be established for either role with any credential.
#   3. pg_stat_activity is checked cluster-wide for both roles; an active client session
#      refuses the run and LOGIN is restored inside the same session — still under
#      boundary ownership — before the lock is released.
#   4. Both passwords rotate and LOGIN is restored inside one atomic subtransaction; a
#      failure rolls the rotation back and the handler restores LOGIN, still under
#      ownership, before the run exits nonzero.
#   5. If the session dies between steps 2 and 4 (crash/connection loss), the lock is
#      released with the boundary left active; restore_login below re-acquires the lock
#      and completes the restoration — serialized, so it can never fire inside another
#      owner's boundary.
set -Eeuo pipefail
set +x  # never trace: credentials reach psql only via the stdin \set stream below

: "${POSTGRES_USER:?set POSTGRES_USER}"
: "${POSTGRES_DB:?set POSTGRES_DB}"
: "${POSTGRES_MIGRATION_PASSWORD:?set POSTGRES_MIGRATION_PASSWORD}"
: "${BLACKBREAD_RUNTIME_DB_PASSWORD:?set BLACKBREAD_RUNTIME_DB_PASSWORD}"

MAINT_ROLE=blackbread_maint
# Advisory-lock key 727274 (in the SQL below) serializes reconciliation and
# restoration; it is a stable constant, never derived from secrets, and mirrors
# ADVISORY_LOCK_KEY in the deployment test suite.

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

# Controlled restoration is serialized under the SAME advisory lock: it blocks
# until any current owner finishes (or crashes), so it can never mutate a rotated
# role inside another owner's committed boundary. The lock acquire is gated by
# ON_ERROR_STOP=1 (failure aborts before any ALTER); each ALTER then runs
# independently so one missing role cannot strand the other. Harmless when the
# rotation already committed.
restore_login() {
    psql --no-psqlrc -v ON_ERROR_STOP=1 -tAq -U "$MAINT_ROLE" -d "$POSTGRES_DB" \
        >/dev/null 2>&1 <<'SQL' || true
SELECT pg_advisory_lock(727274);
\set ON_ERROR_STOP off
ALTER ROLE blackbread_migration LOGIN;
ALTER ROLE blackbread_app LOGIN;
SELECT pg_advisory_unlock(727274);
SQL
}

# psql \set quoting: wrap in single quotes with '' escaping; values then travel on
# stdin (never argv) and are bound into SQL literals via :'name'.
_psql_quote() {
    printf "'%s'" "${1//\'/\'\'}"
}

# The marker proves the boundary was entered: only then may restoration run. A
# lock-acquisition refusal exits before the marker and never mutates a role.
output=$({
    printf '\\set migration_password %s\n' "$(_psql_quote "$POSTGRES_MIGRATION_PASSWORD")"
    printf '\\set runtime_password %s\n' "$(_psql_quote "$BLACKBREAD_RUNTIME_DB_PASSWORD")"
    cat <<'SQL'
-- Phase 1: advisory lock. Refusal exits BEFORE any mutation, so a competing run
-- can never restore LOGIN inside this owner's committed boundary.
DO $$
BEGIN
    IF NOT pg_try_advisory_lock(727274) THEN
        RAISE EXCEPTION 'another credential reconciliation holds the advisory lock';
    END IF;
END
$$;
\echo __BB_BOUNDARY_OWNED__
-- Phase 2: committed NOLOGIN boundary — from this instant no new session can be
-- established for either rotated role with any credential.
ALTER ROLE blackbread_migration NOLOGIN;
ALTER ROLE blackbread_app NOLOGIN;
-- Phase 3: cluster-wide session check (pg_stat_activity covers all databases;
-- only client logins block rotation — background workers run as the bootstrap
-- superuser and are ignored). Refusal restores LOGIN inside this session, still
-- under boundary ownership, then exits nonzero.
SELECT EXISTS (
    SELECT 1 FROM pg_stat_activity
    WHERE pid <> pg_backend_pid()
      AND backend_type = 'client backend'
      AND usename IN ('blackbread_migration', 'blackbread_app')
) AS has_active
\gset
\if :has_active
    ALTER ROLE blackbread_migration LOGIN;
    ALTER ROLE blackbread_app LOGIN;
    DO $$ BEGIN RAISE EXCEPTION 'active blackbread_migration/blackbread_app sessions exist; refusing to rotate'; END $$;
\endif
-- Phase 4: atomic rotate + LOGIN inside one subtransaction. A failure rolls the
-- rotation back and the handler restores LOGIN — still under ownership — before
-- the run reports the failure. Passwords reach the server only via the temp
-- table bound from psql variables (psql does not interpolate inside $$ bodies).
CREATE TEMP TABLE _bb_reconcile(migration_pw text, runtime_pw text, ok boolean);
INSERT INTO _bb_reconcile(migration_pw, runtime_pw)
    VALUES (:'migration_password', :'runtime_password');
DO $$
DECLARE
    m text;
    r text;
BEGIN
    SELECT migration_pw, runtime_pw INTO m, r FROM _bb_reconcile;
    BEGIN
        EXECUTE format('ALTER ROLE blackbread_migration WITH LOGIN PASSWORD %L', m);
        EXECUTE format('ALTER ROLE blackbread_app WITH LOGIN PASSWORD %L', r);
        UPDATE _bb_reconcile SET ok = true;
    EXCEPTION WHEN OTHERS THEN
        BEGIN
            EXECUTE 'ALTER ROLE blackbread_migration LOGIN';
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
        BEGIN
            EXECUTE 'ALTER ROLE blackbread_app LOGIN';
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
        UPDATE _bb_reconcile SET ok = false;
    END;
END
$$;
SELECT ok FROM _bb_reconcile
\gset
\if :ok
\else
    DO $$ BEGIN RAISE EXCEPTION 'credential rotation failed; LOGIN restored under boundary ownership'; END $$;
\endif
SQL
} | _psql -U "$MAINT_ROLE" -d "$POSTGRES_DB" -f - 2>&1) && rc=0 || rc=$?

if [ "$rc" -ne 0 ]; then
    grep -v '__BB_BOUNDARY_OWNED__' <<<"$output" >&2 || true
    if grep -q '__BB_BOUNDARY_OWNED__' <<<"$output"; then
        # The boundary was entered; make sure LOGIN is restored, serialized
        # under the same advisory lock (no-op when already restored).
        restore_login
        echo "credential reconciliation did not complete; LOGIN restored" >&2
    else
        echo "credential reconciliation refused; nothing was changed" >&2
    fi
    exit 1
fi

echo "database credentials rotated"
