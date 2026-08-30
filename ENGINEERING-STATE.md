# BlackBread Engineering State

This file records the repository owner's selected work sequence. It is not proof of implementation
and never overrides live GitHub, accepted architecture, delivery policy, tests, or open gaps.

## State metadata

* **State:** ACTIVE
* **Current milestone:** M1 — Trust Spine
* **Last verified:** 2026-08-30 UTC
* **Protected main baseline:** `beb7edfac6558f2d776664cd20eda8df8030b0fe`
* **Last merged PR:** `#30` (governance: add anti-spaghetti and supply-chain gates)
* **Active ruleset:** `main-branch-protection` (`21644438`)
* **Contractual gate:** first-party CI (`quality`, `tests`, `security`, `governance`) +
  `GitGuardian Security Checks` + review-thread resolution + branch currency (live ruleset
  conformance verified by GOV-GAP-001)

These values are checkpoints to verify, not facts to trust without querying live GitHub.

## Current decision

PR #30 introduced deterministic size gates, but legacy oversized files are admitted through
editable numeric exceptions. PR #31 then demonstrated that an agent can increase an exception in
the same pull request. The repository owner selected one corrective governance slice before
resuming M1: derive legacy allowances from the protected base and make cap increases fail closed.

The source workflow is only bootstrap evidence until the live ruleset requires its
`quality-budget` check. No session may claim the size policy is unbypassable before that live
activation and machine-contract synchronization are verified.

## Next selected slice

* **ID:** PR-Q1
* **Title:** Protected Quality Budget Foundation
* **State:** IN PROGRESS
* **Owner:** governance
* **Purpose:** replace editable size exceptions with protected-base allowances and install a
  base-controlled evaluator that never executes pull-request code.

### Required scope

* fixed caps of 400 production-module lines, 50 function lines, and 500 test-module lines;
* no editable legacy oversize list;
* protected-base non-growth for existing oversized modules and functions;
* renamed oversized files treated as new files;
* cap decreases allowed and cap increases denied;
* a read-only `pull_request_target` evaluator that checks Git objects as data and never executes
  pull-request code;
* focused negative tests for cap increases and legacy-size growth.

### Architecture boundaries

Keep the pure size policy separate from Git/ref access and workflow orchestration. Do not create a
generic governance manager, quality service, scanner registry, or shared utility dumping ground.

### Non-goals

PR-Q1 does not add subjective AI-slop word lists, test anti-pattern scanners, CI aggregation,
CodeRabbit PAT automation, production capabilities, or a live ruleset mutation. It must not claim
the quality budget is required until the live ruleset and machine contract are synchronized.

## Planned sequence after PR-Q1

Subject to live evidence and a fresh owner decision:

1. Activate and verify the `quality-budget` required check, then synchronize the machine contract.
2. Resume PR-M1.2 — PostgreSQL Tenant Isolation Foundation.
3. PR-M1.3 — Deterministic Graph Projection and NetworkX Rebuild.
4. PR-M1.4 — Policy Kernel v1.
5. PR-M1.5 — Execution Lease and Deterministic Conductor Path.
6. PR-M1.6 — Dual Kill Switch.

This sequence is planning authority only. Each slice must be revalidated against live architecture,
implementation, tests, risks, and open gaps before work begins.

## Open blockers

The following remain OPEN unless live closure evidence proves otherwise:

* GOV-GAP-001 (live ruleset conformance is not yet verified against the machine contract)
* LEDGER-GAP-001 (R0 trust-spine integration remains incomplete)

Former GOV-GAP-002 through GOV-GAP-005 are CLOSED (WITHDRAWN) with the AI-review gate removal; see
GAP-REGISTER.md. No session may infer closure from this work-state document.

## Update protocol

Update this file when:

* the selected slice changes;
* an in-flight PR is merged, closed, superseded, or materially rescoped;
* a prerequisite or blocker changes;
* live evidence invalidates the expected checkpoint;
* the repository owner selects the following slice.

Do not update it merely to make implementation appear complete. Completion remains proven by live
code, migrations, tests, CI, review evidence, and release records.
