# GitHub Merge Readiness Smoke Qualification

This document defines the reproducible authenticated exact-head smoke procedure for the merge readiness CLI.

## Objective

Prove that the governance CLI classification path successfully loads a live delivery contract, collects real GitHub API evidence without raising parsing or network exceptions, and evaluates readiness deterministically without making any GitHub mutations.

## Prerequisites

- Python 3.12, `uv` lockfile synchronized.
- A valid, scoped `GITHUB_TOKEN` with repository read access.
- An open pull request against `main` that is ready to merge.

## Procedure

Run the CLI from an environment where `GITHUB_TOKEN` is securely exported (e.g., from your vault or `.env`), strictly without echoing the token into shell history or process arguments:

```shell
# Ensure GITHUB_TOKEN is securely exported in your environment first.
uv run python -m blackbread.governance.merge_readiness_cli \
    --repository carlitotate12160-tech/BlackBread \
    --pull-request <PR_NUMBER> \
    --expected-head-sha <LOWERCASE_40_HEX_HEAD_SHA>
```

## Exit Contract

- **Exit 0**: The canonical output reports `{"status":"ready", "ready":true, ...}` with an empty blockers list. This confirms complete readiness.
- **Exit 1**: The canonical output reports `{"status":"not_ready", "ready":false, ...}` with an allowlisted array of substantive `blockers`.
- **Exit 2**: The canonical output reports `{"status":"error", "ready":false, ...}` with an array of `errors` due to invalid inputs, partial evidence, or transport failure.

## Token Redaction and Safety Rules

- Never log or print `GITHUB_TOKEN`.
- Do not poll or construct a retry loop around this command.
- Do not use the output of this command as authorization to perform an automated merge.
- The repository owner always retains final manual merge authority.

## Evidence Schema

The sanitized canonical JSON output format expected during a smoke test run is:

```json
{"blockers":["BLOCKING_MERGE_STATE","CODE_SCANNING_ANALYSIS_MISSING","REQUIRED_CHECK_MISSING"],"expected_head_sha":"<SHA>","pull_request":<PR_NUMBER>,"ready":false,"repository":"<OWNER>/<REPO>","schema_version":1,"status":"not_ready"}
```
