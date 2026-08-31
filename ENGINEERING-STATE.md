# BlackBread Engineering State

This file records the repository owner's selected work sequence. It is not proof of implementation
and never overrides live GitHub, accepted architecture, delivery policy, tests, or open gaps.

## State metadata

* **State:** ACTIVE
* **Current milestone:** M1 — Trust Spine
* **Last verified:** 2026-08-31 UTC
* **Protected main baseline:** `2230d93` (PR #35 — deterministic scope graph replay spine)
* **Last merged PR:** `#35` (feat: add deterministic scope graph replay spine)
* **Active ruleset:** `main-branch-protection` (`21644438`)
* **Contractual gate:** union of the live required checks (`quality`, `tests`, `security`,
  `governance`, `GitGuardian Security Checks`) and machine contract (`ci-ok`,
  `GitGuardian Security Checks`), plus review-thread resolution and branch currency. The mismatch
  remains `GOV-GAP-001`; it is not waived by this state file.

These values are checkpoints to verify, not facts to trust without querying live GitHub.

## Current decision

Two governance PRs merged in sequence:

* **PR #31** (Alpha): protected-base size budgets — `quality-budget` workflow, `size_budget.py`
  module, `check_size_budget.py` script, `quality-budgets.json` config. Legacy oversize exceptions
  derived from protected base; cap increases fail closed.
* **PR #32** (Devin): restored ci-ok aggregator, CodeRabbit auto-trigger, banned patterns (13
  tests), AI-slop detection (5 tests), diff budget, advisory AI review policy with safety-critical
  binding, GAP-REGISTER sync, ci-ok governance tests (3 tests in `test_ci_ok_aggregator.py`).

The repository now has both the protected-base size budget system (PR #31) and the Decepticon-style
quality gates (PR #32): banned patterns, AI-slop signatures, diff budget, ci-ok aggregator, and
CodeRabbit auto-trigger.

## What is now live on main

### From PR #30 (anti-spaghetti + supply-chain gates)

* Production module ≤400 lines, function ≤50 lines, McCabe ≤10
* Test module ≤500 lines with shrink-only exceptions
* No circular imports, no duplicate test names
* Docker images digest-pinned, GitHub Actions SHA-pinned
* No floating version constraints
* Active capabilities must have supply-chain pins

### From PR #31 (protected-base size budgets)

* `quality-budget` workflow (`pull_request_target`, read-only, base-controlled)
* `src/blackbread/governance/size_budget.py` — pure policy module
* `scripts/check_size_budget.py` — CLI evaluator
* `config/quality-budgets.json` — caps config
* Legacy oversize exceptions derived from protected base SHA
* Cap decreases allowed; cap increases denied

### From PR #32 (ci-ok + quality gates)

* `ci-ok` aggregator job in `ci.yml` (aggregates quality, tests, security, governance)
* `ci-ok` fails on any non-success result (failure, cancelled, skipped)
* `coderabbit-trigger.yml` — auto-trigger CodeRabbit via PAT comment (advisory, non-blocking)
* `test_banned_patterns.py` — 13 tests: bare except, except-pass, type-ignore, noqa, print,
  suppressed returns, NotImplementedError, TODO, if-true-else-false, vague names, flag words,
  speculative kwargs, diff budget
* `test_ci_ok_aggregator.py` — 3 tests: ci-ok exists with `if: always()`, needs all required jobs,
  fails on non-success
* Diff budget: ≤400 runtime lines, ≤10 runtime files (excludes docs/config)
* Advisory AI review policy with safety-critical binding (CodeRabbit FULL required for
  safety-critical paths; Qodo fallback for non-safety-critical only)
* `GAP-REGISTER.md` updated to reference ci-ok aggregator
* `.github/agent-delivery.json` updated: required_status_checks = ci-ok + GitGuardian

### From PR #35 (M1.3a — deterministic ScopeRoot graph projection)

* `engagement.attested` v1 projects deterministic `ScopeRoot` nodes (root_domain, exact_host,
  exact_address, cloud_tenant) into durable PostgreSQL.
* `engagement.stopped` v1 is a graph no-op only after a positive attestation.
* Ledger replay uses one `REPEATABLE READ`, `READ ONLY` snapshot; events are delivered only after the
  full chain/anchor verdict.
* Projection metadata binds manifest hash, validity interval, source sequence, source event hash,
  schema name/version.
* PostgreSQL FK `fk_graph_projection_snapshot_anchor` binds the projection anchor to the immutable
  ledger event.
* PostgreSQL trigger `graph_nodes_attested_provenance` rejects any `graph_nodes` row that does not
  match its source `engagement.attested` payload exactly.
* NetworkX view is deeply frozen and carries `tenant_id` + `engagement_id` on every node.
* State-root v1 golden vector is frozen.

### What is NOT yet live

* `quality-budget` is NOT a required status check in the live ruleset (only `quality`, `tests`,
  `security`, `governance`, `GitGuardian Security Checks` are required)
* `ci-ok` is NOT yet a required status check in the live ruleset (the same five individual checks
  remain required)
* CodeRabbit trigger transport has run successfully, but CodeRabbit skips automatic review for
  repositories with fewer than 10 stars; safety-critical PRs still require a manual FULL review on
  their exact current head.
* Test quality bar (mock SUT, tautological tests, vague test names, skip/flaky/pragma) — NOT yet
  implemented
* Self-review checklist — NOT yet in PR template
* End-to-end verification statement — deferred until runtime exists

## Active selected slice

The repository owner has split PR-M1.3b into three sequential sub-slices. PR-M1.3a is now live on
`main`; PR-M1.3b1 is the active implementation slice.

* **ID:** PR-M1.3b1
* **Title:** Versioned Attestation Supersession + Identity/Revision Domain Split
* **State:** ACTIVE
* **Owner:** trust-spine
* **Prerequisite:** PR-M1.3a is squash-merged to `main` at `2230d93`.
* **Purpose:** structural head selection only; clock-free; no temporal `as_of`; no state-root v2.
  Proves `engagement.attested v2` (with `supersedes_event_hash`) is admitted and registered, the
  supersession chain is validated fail-closed, and stable ScopeRoot identity is separated from
  immutable temporal assertion revisions.

### M1.3b1 bounded scope

* Contract sections **A + B** only.
* `engagement.attested v2` payload and registry entry `("engagement.attested", 2)`.
* Supersession chain validation: no predecessor, fork, cycle, sequence-regression, second v1, or
  unsupported v3 fails closed; cross-tenant/cross-engagement substitution fails closed.
* Stable ScopeRoot identity separated from immutable temporal-revision/provenance record.
* Effective scope = the verified chain head's replacement scope in the domain projector, using the
  existing stable identity and state-root v1 preimage.
* State-root v1 preimage and golden vector remain byte-stable for v1-only histories.
* Files: `ledger/catalog.py` (+v2 payload), new `graph/supersession.py` (chain validation + head
  selection), new `graph/revision.py` (immutable revision identity), and bounded projector/replay
  integration.
* No migration or new persistence table. The owner selected a domain-only b1 amendment after live
  `0005` inspection proved that truthful v2 provenance cannot satisfy its v1-only source constraint.
  Lone-v1 publication remains unchanged; a v2 head fails closed before publication until b3 closes
  `GRAPH-GAP-001`.

### M1.3b1 seal gate

PR-M1.3b1 may merge only when the v2 payload is fully registered, the supersession validator rejects
all negative cases, the identity/revision split keeps `ScopeProjector` deterministic, v2 ledger replay
fails before incompatible v1-only publication, all repository gates pass on the exact head, the
current-head CodeRabbit FULL review is complete, and every review thread is dispositioned and
resolved. A merge does not complete M1.3, M1/R0, `GOV-GAP-001`, `LEDGER-GAP-001`, or
`GRAPH-GAP-001`.

### M1.3b split plan (recorded contract)

#### PR-M1.3b2 — Temporal Selection + State-Root v2

* **State:** DECIDED
* **Prerequisite:** b1 merged (uses its revision representation).
* **Contract sections:** C + D, plus NetworkX `as_of` view.
* **Purpose:** clock-free temporal selection and v2 state root binding the full supersession history
  (stable identities, every immutable revision, predecessor linkage, lineage head, exact provenance,
  schema/version, and scope-canonicalization/catalog version).
* **Non-goals at b2:** no new persistence schema; no `0006` migration; publication still uses existing
  `0005` tables.

#### PR-M1.3b3 — Durable Temporal Projection Lifecycle

* **State:** DECIDED
* **Prerequisite:** b2 merged (needs the v2 root + revision lineage semantics it must persist).
* **Contract sections:** E + the persistence half of F.
* **Purpose:** immutable attestation-revision lineage + stable membership persisted separately from
  the replaceable materialized head; atomic publish preserves history; `read()` recomputes the v2
  history-binding root from persisted lineage; close `GRAPH-GAP-001` and enable truthful v2-head
  publication.
* **Files:** new `migrations/versions/0006_m1_temporal_scope_graph.py` (excluded from runtime budget),
  `graph/persistence.py` (+lineage read/publish, v2 read recompute, upgrade path).

### M1.3b cross-cutting risks

* **B1 closure (still OPEN on `main`):** the state-root v1 preimage still omits the scope
  canonicalization/catalog version. PR-M1.3b2 is the correct place to close it structurally by
  pinning that version into the state-root v2 preimage with its own RED test. Until then it is a
  registered risk, mitigated only by the v1 golden vector.
* **Merge-order / governance fence:** `GOV-GAP-001` is OPEN. No b1/b2/b3 may merge under an
  unverified live ruleset without either closing `GOV-GAP-001` first or an explicit, recorded owner
  decision to accept that risk. Building and reviewing may proceed; sealing waits on the fence.
* **Total-consumer invariant (M1.3a N4):** `ScopeProjector.consume()` must explicitly transition or
  no-op every future `agent_events` schema/version; an unknown input fails full replay closed.
* **Domain-only b1 amendment:** `GRAPH-GAP-001` records the owner-selected fail-closed boundary. A v2
  attestation is ledger-durable and domain-replayable, but existing `0005` tables cannot truthfully
  store its source version. Temporal lineage and v2-head persistence remain b3 work.

## Open blockers

The following remain OPEN unless live closure evidence proves otherwise:

* GOV-GAP-001 (live ruleset conformance is not yet verified against the machine contract —
  `ci-ok` not yet required in live ruleset)
* LEDGER-GAP-001 (R0 trust-spine integration remains incomplete)
* GRAPH-GAP-001 (v2 head publication awaits the b3 temporal persistence schema)

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
