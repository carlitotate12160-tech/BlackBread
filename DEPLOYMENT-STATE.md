# BlackBread Deployment State

This document records the live deployment target and sync procedure so that every
new session can verify Oracle matches protected `main` before editing. It is a
coordination pointer, not a substitute for live verification.

Sensitive deployment details (IP, user, path, SSH alias) live in
`DEPLOYMENT-STATE.local.md`, which is git-ignored and never pushed. Copy the
template below into that local file and fill in the real values on your machine.

## Cara akses Oracle via WSL

Semua operasi Oracle dilakukan dari WSL, bukan dari PowerShell/Windows langsung.

1. Buka WSL: `wsl`
2. SSH ke Oracle: `ssh <ORACLE_HOST_ALIAS>`
3. SSH config ada di `~/.ssh/config` (WSL). Lihat `DEPLOYMENT-STATE.local.md`
   untuk nilai asli Host, HostName, User, dan IdentityFile.

## Oracle Cloud VM

- Path: `<ORACLE_REPO_PATH>`
- Branch: `main`
- Docker Compose project: `blackbread` (database + migrate + api)
- Network: `control-plane` (internal, tidak exposed ke publik)
- Architecture: `aarch64` (ARM Ampere)
- CPUs: `<ORACLE_CPU_COUNT>`
- Memory: `<ORACLE_MEMORY>`

## Last verified

- Date: `<VERIFIED_DATE>`
- Main HEAD: `<VERIFIED_MAIN_SHA>`
- Migration: `<VERIFIED_MIGRATION>`
- API status: `<API_STATUS>`
- PostgreSQL status: `<DB_STATUS>`

## Sync procedure (dari WSL)

```bash
wsl
ssh <ORACLE_HOST_ALIAS> "cd <ORACLE_REPO_PATH> && git fetch origin && git merge --ff-only origin/main && [ \"\$(git rev-parse HEAD)\" = \"\$(git rev-parse origin/main)\" ] || exit 1"
ssh <ORACLE_HOST_ALIAS> "cd <ORACLE_REPO_PATH> && docker compose up -d --build"
```

## Verification (dari WSL)

```bash
wsl
ssh <ORACLE_HOST_ALIAS> "cd <ORACLE_REPO_PATH> && git log --oneline -1"
ssh <ORACLE_HOST_ALIAS> "docker exec blackbread-api-1 python -c 'import urllib.request; print(urllib.request.urlopen(\"http://localhost:8000/health/ready\").read().decode())'"
ssh <ORACLE_HOST_ALIAS> "docker exec blackbread-database-1 psql -U blackbread_migration -d blackbread -c 'SELECT version_num FROM alembic_version;'"
```

## Drift handling

Jika Oracle HEAD tidak sama dengan protected `main` HEAD, record sebagai drift.
Sync sebelum mulai slice baru jika drift mempengaruhi slice.
Jangan hand-type SHA di file ini untuk nilai yang belum diverifikasi langsung.

## Local file template

Buat `DEPLOYMENT-STATE.local.md` (sudah di-`.gitignore`) dengan format:

```markdown
# Local deployment values — NEVER COMMIT

- ORACLE_HOST_ALIAS: <alias di ~/.ssh/config>
- ORACLE_HOST_NAME: <IP publik Oracle VM>
- ORACLE_USER: <user SSH>
- ORACLE_IDENTITY_FILE: <path key SSH>
- ORACLE_REPO_PATH: <path repo di VM>
- ORACLE_CPU_COUNT: <jumlah CPU>
- ORACLE_MEMORY: <jumlah memori>
```
