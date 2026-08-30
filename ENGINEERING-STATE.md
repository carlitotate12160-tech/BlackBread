# BlackBread Engineering State

This file records the repository owner's selected work sequence. It is not proof of implementation
and never overrides live GitHub, accepted architecture, delivery policy, tests, or open gaps.

## State metadata

* **State:** ACTIVE
* **Current milestone:** M1 — Trust Spine
* **Last verified:** 2026-08-30 UTC
* **Protected main:** `f40d7204a1890dfdaceb1163cab6408424a64031`
* **Last merged PR:** `#23` — M1: verify ledger from a committed PostgreSQL snapshot
* **Merged PR head (pre-squash):** `dc0d8d77187886c04dad55428394ddea1f148143`
* **Squash-merge commit:** `f40d7204a1890dfdaceb1163cab6408424a64031`
* **Active ruleset:** `main-branch-protection` (`21644438`)
* **AI review gate state:** `bootstrap_not_enforced`

These values are checkpoints to verify, not facts to trust without querying live GitHub.

## Current decision

PR #23, "M1: verify ledger from a committed PostgreSQL snapshot," has been squash-merged into
protected `main` as `f40d7204a1890dfdaceb1163cab6408424a64031`. Post-merge first-party CI
(`CI`, `Push on main`) is verified green on `f40d720`. The bootstrap `AI Review Gate` failure is
expected and not a blocker (`bootstrap_not_enforced`).

A failure from the non-required bootstrap ai-review-gate is not by itself a merge blocker. Do not
modify ai-review-gate as part of any M1 implementation slice.

## Next selected slice

* **ID:** PR-M1.2
* **Title:** PostgreSQL Tenant Isolation Foundation
* **State:** READY
* **Owner:** trust-spine
* **Purpose:** establish explicit, transaction-bound, fail-closed PostgreSQL tenant context and RLS
  for the existing engagements and agent-events paths before adding further tenant-bearing tables.

### Required scope

* validated explicit tenant context;
* transaction-local binding;
* PostgreSQL RLS for existing protected tenant tables (engagements, agent_events, clients);
* missing-context denial;
* cross-tenant read and write denial;
* pooled-connection context cleanup;
* commit, rollback, exception, and cancellation cleanup;
* runtime-role inability to disable or bypass RLS;
* explicit separate administrative and migration authority;
* compatibility with ledger append and independently owned committed-snapshot verification;
* real PostgreSQL integration and privilege tests.

### Architecture boundaries

Separate:

* tenant identifier validation;
* SQLAlchemy transaction/connection binding;
* Alembic policies and grants;
* ledger append behavior;
* ledger verification behavior;
* PostgreSQL integration tests.

Do not create a generic tenant manager, database manager, trust-spine service, utility dumping ground,
hidden global context, implicit session listener, circular dependency, or mixed-responsibility
orchestrator.

Production modules at 320 lines require architecture review. Modules above approximately 400 lines
or functions above approximately 50 lines require cohesive justification or extraction. McCabe
complexity above 10 blocks merge.

### Non-goals

PR-M1.2 does not implement:

* graph projection or NetworkX rebuild;
* Conductor;
* Policy Kernel;
* execution leases;
* kill-switch;
* capability execution;
* AI-review-gate stabilization;
* branch-protection changes;
* unrelated refactoring.

It must not claim authenticated non-spoofable tenant isolation, LEDGER-GAP-001, M1, R0, or any
governance gap closed without the exact required live evidence.

## Planned sequence after PR-M1.2

Subject to live evidence and a fresh owner decision:

1. PR-M1.3 — Deterministic Graph Projection and NetworkX Rebuild
2. PR-M1.4 — Policy Kernel v1
3. PR-M1.5 — Execution Lease and Deterministic Conductor Path
4. PR-M1.6 — Dual Kill Switch
5. R0 conformance review

This sequence is planning authority only. Each slice must be revalidated against live architecture,
implementation, tests, risks, and open gaps before work begins.

## Open blockers

The following remain OPEN unless live closure evidence proves otherwise:

* GOV-GAP-001
* GOV-GAP-002
* GOV-GAP-003
* GOV-GAP-004
* GOV-GAP-005
* LEDGER-GAP-001

No session may infer closure from this work-state document.

## Update protocol

Update this file when:

* the selected slice changes;
* an in-flight PR is merged, closed, superseded, or materially rescoped;
* a prerequisite or blocker changes;
* live evidence invalidates the expected checkpoint;
* the repository owner selects the following slice.

Do not update it merely to make implementation appear complete. Completion remains proven by live
code, migrations, tests, CI, review evidence, and release records.
