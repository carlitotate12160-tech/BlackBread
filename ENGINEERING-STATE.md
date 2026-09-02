# BlackBread Engineering State

This file records the repository owner's selected work sequence. It is not proof of implementation
and never overrides live GitHub, accepted architecture, delivery policy, tests, or open gaps.

## State metadata

* **State:** ACTIVE
* **Current milestone:** M1 — Trust Spine
* **Last verified:** 2026-09-02 UTC
* **Current branch:** `m1-3b3b-harden`
* **Active ruleset:** `main-branch-protection` (`21644438`)
* **Contractual gate:** the live ruleset matches the machine contract. Required status checks are
  `ci-ok` (aggregator for `quality`, `tests`, `security`, `governance`) and `GitGuardian Security
  Checks`. The pull-request rule enforces solo-developer zero approvals, review-thread resolution,
  stale-review dismissal, squash-only merge, and no extra approval for unattributed changes. Branch
  currency is required. `GOV-GAP-001` is CLOSED as of 2026-08-31; `GOV-GAP-006` is OPEN as of
  2026-08-31; see GAP-REGISTER.md.
* **Note on baselines:** the protected `main` HEAD and last merged PR are never hand-typed here.
  `GOV-GAP-006` tracks the post-merge automation that stamps the actual merged SHA. Always verify
  the live `main` HEAD, PR list, and merge state on GitHub.

These values are checkpoints to verify, not facts to trust without querying live GitHub.

## Current decision

The repository owner selected a bounded governance correction after the tiered PR-Agent model change:
canonical changed-path classification must prevent an omitted `safety-critical` label from selecting
advisory review, GitHub lookup failures must fail closed, label identity must match exactly, and a
binding V4-Pro review must not fall back to an advisory model. This correction changes no required
status check and no target-facing capability.

Three governance PRs merged in sequence:

* **PR #31** (Alpha): protected-base size budgets — `quality-budget` workflow, `size_budget.py`
  module, `check_size_budget.py` script, `quality-budgets.json` config. Legacy oversize exceptions
  derived from protected base; cap increases fail closed.
* **PR #32** (Devin): restored ci-ok aggregator, CodeRabbit auto-trigger, banned patterns (13
  tests), AI-slop detection (5 tests), diff budget, advisory AI review policy with safety-critical
  binding, GAP-REGISTER sync, ci-ok governance tests (3 tests in `test_ci_ok_aggregator.py`).
* **PR #38** (Devin): add `.github/workflows/pr-agent.yml` with
  `The-PR-Agent/pr-agent@ab6ec54bfeb37933ddb74259338752e9272016c6` using `DEEPSEEK_API_KEY` and
  `deepseek/deepseek-v4-pro` as the model; add `.pr_agent.toml`; remove the previous fallback
  review provider from the AI review contract; make PR-Agent (DeepSeek) binding for safety-critical
  PRs and CodeRabbit the advisory fallback for non-safety-critical PRs.

The repository now has the protected-base size budget system (PR #31), the Decepticon-style quality
gates (PR #32), and the PR-Agent/CodiumAI DeepSeek review integration (PR #38).

PR-M1.3b2a was released in PR #42 (`aff7df4`). PR-M1.3b2b was released in PR #43 (`f721f72`).
PR-M1.3b3 is the current active slice; it is scoped to durable temporal projection lifecycle
(migration `0006`, immutable revision-lineage persistence, atomic temporal publication, and
`GRAPH-GAP-001` closure).

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
* Advisory AI review policy with safety-critical binding (PR-Agent DeepSeek review required for
  safety-critical paths; CodeRabbit primary for non-safety-critical paths, with PR-Agent fallback)
* `GAP-REGISTER.md` updated to reference ci-ok aggregator
* `.github/agent-delivery.json` updated: required_status_checks = ci-ok + GitGuardian

### From PR #38 (AI review tooling — PR-Agent/CodiumAI with DeepSeek)

* `.github/workflows/pr-agent.yml` — pinned `The-PR-Agent/pr-agent@ab6ec54bfeb37933ddb74259338752e9272016c6`
  with `DEEPSEEK_API_KEY`, model `deepseek/deepseek-v4-pro`, fallback `deepseek/deepseek-v4-flash`
* `.pr_agent.toml` with review instructions, `handle_push_trigger = true`, `push_commands = ["/review"]`
* `pull_request` path: non-draft, same-repo, and main-branch guards; `issue_comment` path: trusted
  user (`OWNER`/`MEMBER`/`COLLABORATOR`) and slash-command guards
* Separate `pull_request` vs `issue_comment` concurrency groups
* AI review contract: PR-Agent (DeepSeek) binding for safety-critical paths, CodeRabbit primary
  advisory for non-safety-critical paths, neither a required status check

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

* `quality-budget` is NOT a required status check in the live ruleset; `ci-ok` is the required
  aggregator and `GitGuardian Security Checks` is the required third-party check, matching
  `.github/agent-delivery.json`. `GOV-GAP-001` is CLOSED.
* CodeRabbit is the primary advisory reviewer for non-safety-critical paths, with PR-Agent as
  fallback advisory; PR-Agent (CodiumAI / DeepSeek) is the binding reviewer for safety-critical
  paths. Neither is a required status check; both must be dispositioned when they produce actionable
  findings.
* Test quality bar (mock SUT, tautological tests, vague test names, skip/flaky/pragma) — NOT yet
  implemented
* Self-review checklist — NOT yet in PR template
* End-to-end verification statement — deferred until runtime exists

## Selected M1.3b slices

The repository owner split the former PR-M1.3b2 after its combined temporal-policy, state-root,
PostgreSQL-replay, and NetworkX runtime diff exceeded both the 320-line architecture threshold and
400-line hard cap. PR-M1.3b1 is RELEASED; PR-M1.3b2a is RELEASED; PR-M1.3b2b is RELEASED;
PR-M1.3b3 is ACTIVE.

### PR-M1.3b1 (released)

* **ID:** PR-M1.3b1
* **Title:** Versioned Attestation Supersession + Identity/Revision Domain Split
* **State:** RELEASED
* **Owner:** trust-spine
* **Prerequisite:** PR-M1.3a is squash-merged to `main` at `2230d93`.
* **Released at:** `e68595a` / PR #36
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

### PR-M1.3b1 seal gate

PR-M1.3b1 may merge only when the v2 payload is fully registered, the supersession validator rejects
all negative cases, the identity/revision split keeps `ScopeProjector` deterministic, v2 ledger replay
fails before incompatible v1-only publication, all repository gates pass on the exact head, the
current-head independent AI review required by the then-active binding review contract is complete
(CodeRabbit for b1, since PR-Agent had not yet been adopted), and every review thread is
dispositioned and resolved. A merge does not complete M1.3, M1/R0, `LEDGER-GAP-001`, or
`GRAPH-GAP-001`.

### PR-M1.3b2a (released)

* **ID:** PR-M1.3b2a
* **Title:** Deterministic Temporal ScopeRoot Selection
* **State:** RELEASED
* **Released at:** `aff7df4` / PR #42
* **Prerequisite:** PR-M1.3b1 RELEASED.
* **Scope:** pure immutable validation of complete attestation-event groups and linear revision
  lineage, canonical explicit timezone-aware `as_of`, half-open validity, monotonic successor
  activation, deterministic gap/expiry behavior, and complete-group effective ScopeRoot selection.
* **Failure modes:** naive or non-normalizable time, malformed revision identity or provenance,
  inconsistent group metadata, duplicate revisions or membership, duplicate source sequence,
  missing/non-linear predecessor, non-monotonic activation, and non-admitted lineage head all fail
  closed.
* **Non-goals:** no state-root v2, canonicalization-version change, v1 hardening, PostgreSQL replay,
  NetworkX view, persistence, migration, publication, or target-facing behavior.
* **Intermediate reachability:** the pure selector is not wired into replay or publication and grants
  no execution authority. The existing `GRAPH-GAP-001` v2-head publication guard is unchanged.
* **Seal criteria:** focused positive/negative temporal tests, affected compatibility suites, all
  repository gates and budgets green, and binding current-head PR-Agent/DeepSeek review complete.
* **Platform qualification:** Oracle ARM64 is unavailable in the current implementation environment
  and is explicitly deferred without an ARM64 result claim. B2a changes no capability, tool, image,
  or client-eligibility state, so the live ARM64 capability-qualification rule is not a per-PR gate.

### PR-M1.3b2b (released)

* **ID:** PR-M1.3b2b
* **Title:** State-Root v2 + Verified Temporal Rebuild + Effective NetworkX View
* **State:** RELEASED
* **Prerequisite:** PR-M1.3b2a released at `aff7df4` / PR #42.
* **Released at:** `f721f72` / PR #43
* **Scope:** state-root v2 over the complete validated temporal lineage; bind the scope
  canonicalization version; harden v1 to reject v2 provenance; verified, read-only, non-persistent
  temporal rebuild from a PostgreSQL snapshot; immutable effective-only NetworkX view with zero edges.
* **B1 disposition:** CLOSED for v2. The v2 canonical preimage includes
  `scope_canonicalization_version`; the v1 known-answer vector and byte preimage remain unchanged for
  v1-only histories; v1 `compute_state_root` rejects v2 provenance.
* **Non-goals:** no migration `0006`; no durable temporal lineage persistence; no v2-head publication;
  no new PostgreSQL schema; no target-facing or authorization changes.
* **Intermediate reachability:** the temporal rebuild path is replay-only; it consumes already-admitted
  v1/v2 events, produces no durable state, and grants no execution authority. The existing
  `GRAPH-GAP-001` v2-head publication guard is preserved.
* **Seal criteria:** focused state-root v2, compatibility, and temporal rebuild tests green; affected
  graph/ledger suites green; all repository gates and budgets green; binding current-head
  PR-Agent/DeepSeek review complete with all findings dispositioned.

### PR-M1.3b3a (released)

* **ID:** PR-M1.3b3a
* **Title:** Durable Temporal Publication
* **State:** RELEASED
* **Released at:** `7afa10f` / PR #45
* **Prerequisite:** PR-M1.3b2b released at `f721f72` / PR #43.
* **Purpose:** migration `0006`, immutable revision-lineage and stable-membership persistence, and atomic temporal publication.
* **Non-goals:** no cold-load reconstruction, no explicit `as_of` projection load, no NetworkX integration (deferred to b3b).

### PR-M1.3b3b-1 (released)

* **ID:** PR-M1.3b3b-1
* **Title:** Verified Temporal Cold Reconstruction + GRAPH-GAP-001 Closure
* **State:** RELEASED
* **Released at:** `05a4b84` / PR #48
* **Prerequisite:** PR-M1.3b3a released at `7afa10f` / PR #45.
* **Purpose:** verified cold reconstruction from durable PostgreSQL temporal rows (`load_temporal_projection`),
  state-root v2 recompute and fail-closed verification against stored snapshot, v1 scope-path guard reword
  confirming v2 provenance rejection, and `GRAPH-GAP-001` closure.
* **Closure evidence:** real-PostgreSQL cold-rebuild proofs in `tests/graph/test_temporal_reconstruction.py`;
  v2 temporal publish path proven working; v1 scope path confirmed rejecting v2 provenance. `GRAPH-GAP-001` gap closed.
* **Non-goals:** no explicit `as_of` durable projection load (b3b-2), no NetworkX cold-load integration (b3b-3).

### PR-M1.3b3b-2+3 (released)

* **ID:** PR-M1.3b3b-2+3
* **Title:** Durable Point-in-Time (as_of) Projection Load + Effective NetworkX Cold-Load View
* **State:** RELEASED
* **Released at:** `ac86548` / PR #49
* **Prerequisite:** PR-M1.3b3b-1 released at `05a4b84` / PR #48.
* **Purpose:** Add an `as_of`-aware durable load over cold-reconstructed lineage (`load_temporal_projection_as_of`), and build the effective NetworkX view from it (`load_temporal_networkx_view_as_of`). Read-only; no schema; no publication change.
* **Non-goals:** no schema change; no change to the durable write/publication path; no changes to authorization/Policy Kernel.

### PR-M1.3b3b-HARDEN (active)

* **ID:** PR-M1.3b3b-HARDEN
* **Title:** Cold reconstruction integrity: verify stable-roots + real cross-tenant isolation
* **State:** IMPLEMENTED
* **Prerequisite:** PR-M1.3b3b-2+3 released at `ac86548` / PR #49.
* **Purpose:** verify cold.roots against the lineage-derived stable-root identity set (F1); add tenant defense-in-depth assert (F4); prove real cross-tenant isolation (F3).
* **Non-goals:** no schema change; no publication change; no valid-input behavior change.

### PR-M1.3b3b-3

* **ID:** PR-M1.3b3b-3
* **Title:** NetworkX Cold-Load Integration
* **State:** SUPERSEDED by PR-M1.3b3b-2+3

### M1.3b cross-cutting risks

* **Append admission:** production exposes only generic `append_event`; no production command or
  publisher currently writes `EngagementAttestedV2`. The b2b replay-only path consumes already-admitted
  v1 and v2 events but does not introduce a v2 writer, so atomic append-time predecessor admission
  remains unreachable from any production path.
* **B1:** CLOSED for v2; the v2 state-root canonical preimage binds
  `scope_canonicalization_version`, and v1 rejects v2 provenance. The v1 known-answer vector and
  preimage remain unchanged.
* **GRAPH-GAP-001:** CLOSED for b3b-1; the durable temporal path publishes v2 heads, cold-rebuild
  proofs verify state-root v2 recomputation, and the v1 scope path correctly rejects v2 provenance.
* **LEDGER-GAP-001:** OPEN; M1/R0 and target-facing execution remain blocked.
* **Total-consumer invariant:** unknown graph event schema/version still fails complete replay closed.

## Open blockers

The following remain OPEN unless live closure evidence proves otherwise:

* LEDGER-GAP-001 (R0 trust-spine integration remains incomplete)

## Closed blockers

* GOV-GAP-001 (live ruleset conformance verified against the machine contract on 2026-08-31 —
  `ci-ok` and `GitGuardian Security Checks` are required in `main-branch-protection`, plus the
  documented solo-developer pull-request controls; see GAP-REGISTER.md for the captured snapshot).
* GRAPH-GAP-001 (closed 2026-09-02; durable temporal publication + cold-rebuild proofs + v1 guard
  reword; see GAP-REGISTER.md for full closure evidence).

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
