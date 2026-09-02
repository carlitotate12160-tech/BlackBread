# BlackBread Deployment State

This document records the live deployment target and sync procedure so that every
new session can verify Oracle matches protected `main` before editing. It is a
coordination pointer, not a substitute for live verification.

## Cara akses Oracle via WSL

Semua operasi Oracle dilakukan dari WSL, bukan dari PowerShell/Windows langsung.

1. Buka WSL: `wsl`
2. SSH ke Oracle: `ssh oracle-alpha`
3. SSH config sudah ada di `~/.ssh/config` (WSL):
   - Host: `oracle-alpha`
   - HostName: `168.110.192.62`
   - User: `ubuntu`
   - IdentityFile: `~/.ssh/id_oracle_alpha`

## Oracle Cloud VM

- Path: `/home/ubuntu/blackbread`
- Branch: `main`
- Docker Compose project: `blackbread` (database + migrate + api)
- Network: `control-plane` (internal, tidak exposed ke publik)
- Architecture: `aarch64` (ARM Ampere)
- CPUs: 2
- Memory: 11.65 GiB

## Last verified

- Date: 2026-09-01
- Main HEAD: `be9e3b7`
- Migration: `0005_m1_scope_graph`
- API status: healthy
- PostgreSQL status: healthy

## Sync procedure (dari WSL)

```bash
wsl
ssh oracle-alpha "cd ~/blackbread && git fetch origin && git merge --ff-only origin/main && [ \"\$(git rev-parse HEAD)\" = \"\$(git rev-parse origin/main)\" ] || exit 1"
ssh oracle-alpha "cd ~/blackbread && docker compose up -d --build"
```

## Verification (dari WSL)

```bash
wsl
ssh oracle-alpha "cd ~/blackbread && git log --oneline -1"
ssh oracle-alpha "docker exec blackbread-api-1 python -c 'import urllib.request; print(urllib.request.urlopen(\"http://localhost:8000/health/ready\").read().decode())'"
ssh oracle-alpha "docker exec blackbread-database-1 psql -U blackbread_migration -d blackbread -c 'SELECT version_num FROM alembic_version;'"
```

## Drift handling

Jika Oracle HEAD tidak sama dengan protected `main` HEAD, record sebagai drift.
Sync sebelum mulai slice baru jika drift mempengaruhi slice.
Jangan hand-type SHA di file ini untuk nilai yang belum diverifikasi langsung.
