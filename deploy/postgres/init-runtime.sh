#!/usr/bin/env bash
set -Eeuo pipefail

: "${BLACKBREAD_RUNTIME_DB_PASSWORD:?set BLACKBREAD_RUNTIME_DB_PASSWORD}"

psql   --set=ON_ERROR_STOP=1   --set=runtime_password="${BLACKBREAD_RUNTIME_DB_PASSWORD}"   --username "${POSTGRES_USER}"   --dbname "${POSTGRES_DB}" <<'SQL'
CREATE ROLE blackbread_runtime
    NOLOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION;
CREATE ROLE blackbread_app
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    PASSWORD :'runtime_password'
    IN ROLE blackbread_runtime;
SQL
