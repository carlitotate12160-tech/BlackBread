# GitHub Merge Readiness Smoke Qualification

Reproducible authenticated, read-only smoke procedure for
`blackbread.governance.merge_readiness_cli`.

## Objective

Prove the CLI loads the trusted schema-v3 delivery contract, collects live
GitHub evidence, and evaluates readiness deterministically — with no GitHub
writes, no retries, and no token exposure.

## Prerequisites

- Python 3.12 with the `uv` lockfile synchronized (`uv sync --locked --all-groups`).
- `GITHUB_TOKEN` exported from a vault or equivalent; it must carry repository
  read access and must never appear in shell history, process arguments, or
  logs.
- The exact head SHA of the pull request under evaluation (lowercase 40-hex).

## Procedure

Run once from the recorded exact implementation commit:

```shell
uv run python -m blackbread.governance.merge_readiness_cli \
    --repository carlitotate12160-tech/BlackBread \
    --pull-request <PR_NUMBER> \
    --expected-head-sha <LOWERCASE_40_HEX_HEAD_SHA>
```

The contract is always read from the trusted repository checkout
(`src/blackbread/governance/` → repository root), never from the current
working directory. A decoy `.github/agent-delivery.json` in CWD is ignored.

## Exit contract

- **0** — valid evaluation, `{"status":"ready","ready":true,...}`, `blockers:[]`.
- **1** — valid complete evaluation, `{"status":"not_ready","ready":false,...}`
  with sorted, unique substantive blocker codes only.
- **2** — invalid arguments or contract, missing token, transport, collection,
  or normalization failure, incomplete/inconsistent evidence, expected-head
  mismatch, or any unclassified blocker: `{"status":"error","errors":[...]}`.

Output is exactly one compact, key-sorted JSON line on stdout. Blocker
details, exception text, remote response text, token material, paths,
GraphQL, and raw evidence are never emitted.

## Safety rules

- Never print or log `GITHUB_TOKEN`.
- Do not wrap the command in a retry or polling loop.
- The result is advisory: it does not authorize a merge, enable auto-merge,
  alter branches, or advance engineering state.
- The repository owner retains sole merge authority.
