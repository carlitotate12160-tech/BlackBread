# BlackBread Engineering State

This file records the repository owner's selected work sequence. It is not proof of implementation
and never overrides live GitHub, accepted architecture, delivery policy, tests, or open gaps.

## State metadata

* **State:** ACTIVE
* **Current milestone:** M1 — Trust Spine
* **Last verified:** 2026-09-05 UTC
* **Current branch:** `m1-4b2a-runtime-gate-contracts`
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

The repository owner selected **Conductor** as the next M1 trust-spine epic. **M1.4a — proposal
contracts and deny-only intake** was released in PR #56 (`3ea51fea`). **M1.4a-FOLLOWUP —
scope-authority leaf** was released in PR #57 (`6739799d`), closing `CONTRACT-GAP-001`.

`ADR-FINAL-003` is **accepted** (DECIDED only, not implemented). It amends `ADR-FINAL-002` §§6, 9, 10,
21, 24, 25, 28, 32, 35, and 36 to define a five-agent, no-central-brain campaign-intelligence
architecture: `WorldSnapshotRef`, coherent `CyberTerrainGraph`/`AttackPathGraph`/
`ControlAssessmentProjection`/`CampaignProjection` views, `CampaignBlackboard`, versioned oracle
contract, bounded `InvestigationTrajectory`, `InvestigationIntent` deduplication, and deterministic
Conductor scheduling. It does not alter M1.4 or authorize target-facing behavior. It introduces
`CAMPAIGN-GAP-001` (P1, OPEN, M3-M5, blocks R1).

The **ADR-FINAL-003 documentation + gap registration** slice was released in PR #58
(`3ab0e392`) and merged to `main`. M1.4a established the Conductor/Policy Kernel contract
boundary: a strict, immutable, versioned `ActionProposal`; a strict, immutable, versioned,
deny-only `PolicyDecision` v1; and a pure deterministic intake function that returns only `DENY`.

M1.4a is deny-only, pure, and non-persistent. The intake boundary reads no database, filesystem,
network, registry file, framework, or wall-clock; the caller supplies the decision UUID and decision
timestamp. Every structurally valid proposal is denied (`PROPOSAL_EXPIRED` when the caller timestamp
is at or past expiry, otherwise `TRUST_SPINE_NOT_READY`) and malformed input fails closed with a typed
validation error before any trusted identity is inferred. M1.4a is not wired to any runtime entry
point, issues no work order, contacts no target, reads no capability registry, and grants no
execution authority. The M1.4a contract makes an `ALLOW` outcome unrepresentable.

### Locked M1.4 (Conductor) sequence

Later sessions must not depend on chat history for this order; each slice remains independently
sealable and fail-closed:

* **M1.4a** — proposal contracts and deny-only intake (this slice). No persistence, work order, lease,
  executor, API exposure, or target effect.
* **M1.4b** — Policy Kernel v1: pure deterministic evaluation of attested policy, target identity,
  capability, every parameter and destination, approvals, budgets, locks, and heat. Still no
  work-order issuance or target effect. **In progress, ACCEPTED WITH CHANGES: split at the trust
  boundary into M1.4b1 (policy admission) and M1.4b2 (runtime gates + final `PolicyDecision` v2).**
  * **M1.4b1** — policy admission: attested engagement policy, target identity, capability
    admission, parameter binding, exhaustive destination manifest, and scope/exclusion checks. An
    admitted result (`ADMITTED_FOR_RUNTIME_GATES`) is non-executable and is not a `PolicyDecision`.
    Further split under the binding 400-line runtime-diff budget into:
    * **M1.4b1a** — verified input-fact snapshot contracts. **RELEASED (PR #60, `6a34f49d`).** No
      evaluator, result, or executable outcome.
    * **M1.4b1b** — pure deterministic admission evaluator + non-executable `AdmissionResult` and
      its result digest, consuming the M1.4b1a snapshots. **RELEASED (PR #61, `4187a053`, merged to
      `main` 2026-09-05).** Non-executable: an admitted result grants no execution authority and is
      not a `PolicyDecision`. Claims no milestone, Policy Kernel v1, R0, or gap complete.
  * **M1.4b2** — runtime gates and final policy decision: approvals, budgets, resource locks, OPSEC
    heat, deterministic outcome precedence, and `PolicyDecision` v2. **ACCEPTED WITH CHANGES: split
    into b2a (input-fact snapshot contracts), b2b, and b2c under the binding 400-line runtime-diff
    budget.**
    * **M1.4b2a** — immutable runtime-gate input-fact contracts (approval grants, budget accounts,
      resource locks, engagement run state, OPSEC heat state, and a digest-bound `RuntimeGateSnapshot`).
      **ACTIVE (branch `m1-4b2a-runtime-gate-contracts`, base `0516cd1a`).** No evaluator, outcome,
      `PolicyDecision` v2, persistence, ledger publication, lease, work order, or target effect.
* **M1.4c** — durable, tenant-isolated, immutable `action_proposals` and `decision_records` with RLS,
  idempotency, ledger provenance, and atomic persistence.
* **M1.4d** — budgets, resource locks, and execution leases; no work order without a valid lease.
* **M1.4e** — dual kill switch and dead-man halt (forensic freeze vs graceful stop) with ledger
  evidence.
* **M1.4f** — deterministic Conductor integration and R0 proof (graph readiness → proposal → Policy
  Kernel → decision → lease → work order, with replay/resume and negative R0 conformance). No target
  executor or capability contact; M2 owns the Capability Gateway and execution path.

M1.4b–M1.4f are recorded here only; they are not implemented in the M1.4a slice.

### Prior governance decision (historical)

The repository owner previously selected a bounded governance correction after the tiered PR-Agent
model change: canonical changed-path classification must prevent an omitted `safety-critical` label
from selecting advisory review, GitHub lookup failures must fail closed, label identity must match
exactly, and a binding V4-Pro review must not fall back to an advisory model. This correction changed
no required status check and no target-facing capability.

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

PR-M1.3b2a was released in PR #42 (`aff7df4`). PR-M1.3b2b was released in PR #43 (`f721f72`). The
M1.3b temporal-projection lifecycle is complete: PR-M1.3b3a (`7afa10f` / PR #45), PR-M1.3b3b-1
(`05a4b84` / PR #48), PR-M1.3b3b-2+3 (`ac86548` / PR #49), and PR-M1.3b3b-HARDEN
(`affef9e0` / PR #52) are RELEASED, closing `GRAPH-GAP-001` and `GRAPH-GAP-002`. PR-M1.4a (Conductor/Policy
Kernel proposal contracts and deny-only intake) was released in PR #56 (`3ea51fea`). PR-M1.4a-FOLLOWUP
(scope-authority leaf — closes CONTRACT-GAP-001) was released in PR #57 (`6739799d`).

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
* `test_banned_patterns.py` — objective code-hygiene and diff-budget governance tests (bare except,
  except-pass, type-ignore, noqa, print, NotImplementedError, TODO, redundant boolean branching,
  structured kwargs with canonical Unpack[TypedDict], diff budget). Subjective word/name blacklists
  and return-suppression bans removed (PR-GOV-AISLOP1); meaningful comments and docstrings are
  preserved; subjective prose quality is review-owned.
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
the PR-M1.3b3 durable-temporal chain (b3a, b3b-1, b3b-2+3, b3b-HARDEN) is RELEASED. PR-M1.4a is the
active slice.

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

### PR-M1.3b3b-HARDEN (released)

* **ID:** PR-M1.3b3b-HARDEN
* **Title:** Cold reconstruction integrity: verify stable-roots + real cross-tenant isolation
* **State:** RELEASED
* **Released at:** `affef9e0548aa11c1a94fef501bd75bd813d8c12` / PR #52 (squash-merged; reverified live on
  2026-09-03 against GitHub: protected `main` HEAD, PR #52 `state: MERGED`, source head
  `44c3ea50c452905426b0aa2cec337234a25d9252`, 0 open PRs).
* **Prerequisite:** PR-M1.3b3b-2+3 released at `ac86548` / PR #49.
* **Purpose:** verify cold.roots against the lineage-derived stable-root identity set (F1); add tenant defense-in-depth assert (F4); prove real cross-tenant isolation (F3).
* **Non-goals:** no schema change; no publication change; no valid-input behavior change.
* **Closure evidence:** `GRAPH-GAP-002` CLOSED (see GAP-REGISTER.md).

### PR-M1.4a (released)

* **ID:** PR-M1.4a
* **Title:** Proposal contracts and deny-only intake
* **State:** RELEASED (PR #56, `3ea51fea`, merged 2026-09-04)
* **Prerequisite:** PR-M1.3b3b-HARDEN released at `affef9e0` / PR #52.
* **Purpose:** establish the Conductor/Policy Kernel contract boundary — strict immutable versioned
  `ActionProposal` (`blackbread.conductor.contracts`) with a deterministic proposal digest over a
  versioned canonical preimage; strict immutable versioned deny-only `PolicyDecision` v1
  (`blackbread.policy.contracts`); and a pure deny-only intake
  (`blackbread.conductor.intake`) that binds tenant, engagement, proposal, digest, and graph version
  exactly and returns only `DENY`.
* **Contract facts:** proposals bind a `GraphVersionReference` (state-root version, projector version,
  state root, ledger event count, ledger head hash) rather than an unbound integer; capability IDs
  reuse the registry's versioned `*.v<N>` form without adding a competing version authority; the
  parameter envelope carries a declared input-schema reference and an immutable canonical snapshot but
  claims no capability-registry admission; canonicalization reuses the ledger's
  `canonical_json`/`sha256_hex`/`canonical_timestamp` primitives.
* **Reason codes:** `PROPOSAL_EXPIRED`, `TRUST_SPINE_NOT_READY`. `ALLOW`, `APPROVAL_REQUIRED`, lease,
  work order, and executable token are unrepresentable in M1.4a.
* **Non-goals:** no migration, `action_proposals`/`decision_records` tables, ledger publication,
  Policy Kernel evaluator, capability-registry eligibility, scope/destination validation, approvals,
  budgets, locks, leases, work orders, kill switch, API/FastAPI endpoint, app wiring, executor, target
  or control-plane egress, agent cognition, or `LEDGER-GAP-001` closure. M1.4a does not claim M1 or R0
  is implemented, verified, released, or production-ready.
* **Intermediate reachability:** the intake is pure and not wired to any runtime entry point; it
  creates no executable decision, so the ADR requirement to ledger every executable policy decision
  remains future M1.4c work.
* **Known debt (CONTRACT-GAP-001):** CLOSED by PR-M1.4a-FOLLOWUP (this slice). `TargetReference`
  canonicalization previously reused `canonical_scope_value` from `blackbread.graph.domain`, coupling
  the trust-spine contract to the graph read-model (layer inversion + duplicate scope types). The
  follow-up slice extracts a pure-stdlib `blackbread.scope.canonical` leaf and reroutes
  `conductor.contracts` and `ledger.catalog` through it (importing a proposal contract pulls 0 graph
  modules, was 4). Residual: `graph.revision.ScopeKind` / `graph.domain.canonical_scope_value` remain
  graph-internal copies (converging them touches released graph-projection code). See GAP-REGISTER.md.
* **Safety-critical coverage:** `blackbread.conductor.*` added to the `pyproject.toml`
  safety-critical coverage include (`blackbread.policy.*` was already present); no threshold lowered.
* **Seal criteria:** focused positive/negative contract, digest, intake, and boundary tests green;
  affected governance suites green; all repository gates and budgets green; binding current-head
  PR-Agent (DeepSeek V4-Pro) review complete with all actionable findings dispositioned.

### PR-M1.4a-FOLLOWUP (released)

* **ID:** PR-M1.4a-FOLLOWUP
* **Title:** Scope-authority leaf (close CONTRACT-GAP-001)
* **State:** RELEASED (PR #57, merged 2026-09-04; base `main` `3ea51fea`)
* **Prerequisite:** PR-M1.4a released at `3ea51fea` / PR #56.
* **Purpose:** close CONTRACT-GAP-001 by extracting the canonical scope authority to a pure-stdlib
  `blackbread.scope.canonical` leaf, removing the layer inversion and duplicate canonical types left
  by M1.4a. The conductor trust-spine contract must not depend on the graph read-model for value
  canonicalization.
* **Contract facts:** new `blackbread.scope.canonical` (re, ipaddress only; no pydantic, no I/O, no
  framework, no other `blackbread` package) single-sources `ScopeKind`/`SCOPE_KINDS` and the canonical
  validators (`canonical_text`, `ensure_canonical_text`, `canonical_domain`, `canonical_address`,
  `canonical_target_value`, `canonical_scope_value`). `conductor.contracts` imports the authority from
  `scope.canonical` instead of `blackbread.graph.domain`; the `_canonical_text` fork is removed;
  `TenantId`/`KeyText`/`CanonicalText` use `ensure_canonical_text`; `TargetKind`/`TARGET_KINDS` alias
  the shared `ScopeKind`/`SCOPE_KINDS`; the identity validator catches `ValueError` (scope) instead of
  `GraphProjectionError` (graph). `ledger.catalog` imports the same validators (no private copy);
  `ScopeExclusion` dispatches through `canonical_target_value`.
* **Non-goals:** no behavior change to `ActionProposal`, `PolicyDecision` v1, or deny-only intake; no
  migration; no convergence of `graph.revision.ScopeKind` / `graph.domain.canonical_scope_value`
  (touches released graph-projection code, tracked as CONTRACT-GAP-002); no SQLAlchemy
  transitive-import fix (pre-existing, boundary test blind to transitive imports).
* **Seal criteria:** `tests/scope/test_canonical.py` plus updated `tests/conductor/test_boundaries.py`
  green; conductor pulls 0 graph modules; all repository gates and budgets green; binding current-head
  PR-Agent (DeepSeek V4-Pro) review complete with all actionable findings dispositioned.
* **Residual:** CONTRACT-GAP-001 is CLOSED at the conductor/ledger layer; the graph-internal copies
  remain a smaller residual tracked as CONTRACT-GAP-002 in GAP-REGISTER.md for a future
  graph-convergence slice.

### PR-M1.4b1a (released)

* **ID:** PR-M1.4b1a
* **Title:** Policy-admission input-fact snapshot contracts
* **State:** RELEASED (PR #60, `6a34f49d`, merged to `main`)
* **Prerequisite:** PR-M1.4a-FOLLOWUP released at `6739799d` / PR #57; ADR-FINAL-003 documentation
  released at `3ab0e392` / PR #58 (post-merge cleanup `5617e8c9` / PR #59).
* **Purpose:** define the strict, frozen, versioned input contracts a caller supplies to policy
  admission — `EngagementPolicySnapshot` (tenant/engagement, policy schema+digest, attestation
  reference+digest, validity interval, canonical scope allow/exclusions, closed-world allowed
  capability IDs, graph/ledger anchor), `TargetIdentitySnapshot` (tenant/engagement, proposal
  digest, exact target, achieved tier, verified/expiry timestamps, graph anchor, verifier
  reference+digest), `CapabilityAdmissionSnapshot` (registry schema+digest, capability ID, owner,
  closed ADR lifecycle, input schema, risk class, required tier, approval class, network path,
  supply-chain digest, bound extractor identity+digest, structural budget ceilings), and
  `DestinationManifest`/`ScopedDestination` (proposal digest, canonical parameter digest, extractor
  binding, bounded unique canonical destinations). Plus `parameter_digest` binding a manifest to a
  proposal's canonical parameters.
* **Contract facts:** every snapshot carries provenance references and digests, never a bare
  `attested`/`verified` boolean; canonical scalar and target types are reused from
  `blackbread.conductor.contracts` (no duplicate scope authority, no graph coupling); the capability
  lifecycle vocabulary is the closed ADR-FINAL-002 §20.2 set; iterables are bounded and destinations
  must be canonical and unique. Contracts are `extra="forbid"`, frozen, and strict.
* **Non-goals (explicitly not in this PR):** no `AdmissionResult`, no admission evaluator, no
  `ADMITTED_FOR_RUNTIME_GATES` or any executable outcome, no deny reason enum, no result digest, no
  `PolicyDecision` v2, no approvals/budgets/locks/heat, no registry loading, no extractor/renderer,
  no persistence, migration, ledger write, API, executor, or target/control-plane egress. It does
  not reinterpret `TRUST_SPINE_NOT_READY` and leaves `ActionProposal` v1, `PolicyDecision` v1, and
  `conductor.intake` unchanged. It claims no milestone, Policy Kernel v1, R0, or gap complete.
* **Intermediate reachability:** these are input contracts with no consumer in this PR; they grant
  no authority and produce no decision. `blackbread.policy.*` is already in the safety-critical
  coverage include; no threshold is changed.
* **Seal criteria:** `tests/policy/test_admission_contract.py` and `tests/policy/test_admission_digest.py`
  plus the updated `tests/conductor/test_boundaries.py` green; conductor/policy pull 0 graph modules;
  all repository gates and budgets green; binding current-head PR-Agent (DeepSeek V4-Pro) review
  complete with all actionable findings dispositioned.
* **Next:** PR-M1.4b1b — the pure deterministic admission evaluator and non-executable
  `AdmissionResult` (with result digest), consuming these snapshots. Then M1.4b2 — runtime gates and
  `PolicyDecision` v2.

### PR-M1.4b1b (released)

* **ID:** PR-M1.4b1b
* **Title:** Pure deterministic policy-admission evaluator
* **State:** RELEASED (PR #61, `4187a053`, merged to `main` 2026-09-05)
* **Prerequisite:** PR-M1.4b1a RELEASED (`6a34f49d` / PR #60).
* **Purpose:** add `blackbread.policy.admission.evaluate_admission`, a pure deterministic function
  that maps the M1.4b1a verified-fact snapshots to a non-executable `AdmissionResult` in fixed
  fail-closed precedence, plus the `AdmissionResult` contract, the closed `AdmissionDenyReason`
  vocabulary, and a self-describing `result_digest` bound over the result's own contents.
* **Contract facts:** the evaluator is pure — no wall clock, UUID generation, I/O, environment, or
  global state (enforced by `tests/conductor/test_boundaries.py`); it reuses the conductor's
  canonical scalar/target types with no graph coupling. Scope **exclusions** use overlap semantics
  (a broad target or destination that contains a narrower excluded host is denied); allow-list
  containment stays deliberately directional. `AdmissionResult` is `extra="forbid"`, frozen, strict;
  `result_digest` is a bound field that the model recomputes and rejects on mismatch, so a tampered
  serialization fails validation. The factory validates its shared input-field schema before
  hashing; malformed or missing fields raise validation errors, and valid nested graph mappings
  are validated before digest construction. Deserialization still requires the result digest.
* **Non-goals (explicitly not in this PR):** no `PolicyDecision` v2, no approvals/budgets/locks/OPSEC
  heat, no runtime gates, no registry loading, no extractor/renderer, no persistence, migration,
  ledger write, API, executor, work order, lease, or target/control-plane egress. An admitted result
  (`ADMITTED_FOR_RUNTIME_GATES`) grants no execution authority and is not a `PolicyDecision`. Leaves
  `ActionProposal` v1, `PolicyDecision` v1, deny-only `conductor.intake`, and ADR-003 campaign
  boundaries unchanged. Claims no milestone, Policy Kernel v1, R0, or gap complete.
* **Known deferral:** the OFFLINE/`NONE` network-path vs target-identity-tier incompatibility is
  recorded as `CONTRACT-GAP-003` (deferred to M5/R1); this PR does not coerce `NONE` to `T0`.
* **Next:** M1.4b2a — immutable runtime-gate input-fact contracts.

### PR-M1.4b2a (active)

* **ID:** PR-M1.4b2a
* **Title:** Immutable runtime-gate input-fact contracts
* **State:** ACTIVE (branch `m1-4b2a-runtime-gate-contracts`, base `main` `0516cd1a`)
* **Prerequisite:** PR-M1.4b1b RELEASED (`4187a053` / PR #61).
* **Purpose:** add `blackbread.policy.runtime_contracts`, strict frozen versioned input-fact
  contracts for the runtime-gate boundary: `ApprovalGrantSnapshot`, `BudgetAccountSnapshot`,
  `RuntimeBudgetSnapshot`, `ResourceLockSnapshot`/`HeldEngagementLock`, `EngagementRunStateSnapshot`,
  `OpsecStateSnapshot`, and a self-describing `RuntimeGateSnapshot` with a canonical snapshot digest.
* **Contract facts:** every snapshot is `extra="forbid"`, frozen, strict, and provenance-bound; the
  top-level `RuntimeGateSnapshot` rejects cross-tenant, cross-engagement, cross-proposal,
  cross-admission-result, cross-capability, and cross-agent substitution among nested facts before
  hashing; the snapshot digest covers schema identity/version and every nested semantic and
  provenance field. Canonical scalar, target, approval, UTC, and digest authorities are reused from
  `blackbread.conductor.contracts`, `blackbread.policy.admission_contracts`, and
  `blackbread.ledger.hashing`; no new scope authority or canonical timestamp logic is added.
* **Non-goals (explicitly not in this PR):** no runtime-gate evaluator, `RuntimeGateResult`,
  `PolicyDecision` v2, `ALLOW`, `APPROVAL_REQUIRED`, `WAIT_FOR_RESOURCE`, `STALE_CONTEXT`,
  `ENGAGEMENT_STOPPED`, or `OPSEC_HOLD` outcome; no persistence, migration, ledger publication, API,
  executor, lease, work order, capability contact, target/control-plane egress, OPSEC transition
  logic, kill-switch logic, or target-facing action. Actual budget, lock, run, and OPSEC state remain
  future ledger/service responsibility; these are immutable value snapshots only.
* **Seal criteria:** focused positive/negative contract, digest, and boundary tests green; affected
  policy and conductor suites green; all repository gates and budgets green; binding current-head
  PR-Agent (DeepSeek V4-Pro) review complete with all actionable findings dispositioned.
* **Next:** M1.4b2b.

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

* LEDGER-GAP-001 (P0; R0 trust-spine integration remains incomplete; M1.4a does not close it).
* GOV-GAP-006 (P1; post-merge `ENGINEERING-STATE.md` main-SHA pointer automation still missing;
  non-blocking per AGENTS.md and `.devin/rules/blackbread.md` preflight rule #10).
* CONTRACT-GAP-002 (P2; `graph.revision.ScopeKind` / `graph.domain.canonical_scope_value` remain
  graph-internal copies after PR-M1.4a-FOLLOWUP closed the conductor/ledger layer inversion of
  CONTRACT-GAP-001. Converging them touches released graph-projection code and is a separate future
  graph-convergence slice. See GAP-REGISTER.md.)
* CAMPAIGN-GAP-001 (P1; campaign coherence and coherent multi-view world snapshot are not implemented.
  `ADR-FINAL-003` is accepted (DECIDED only, not implemented). M1/R0 and M1.4b are not blocked; R1
  and every target-facing release are blocked until M3-M5 closure. See GAP-REGISTER.md.)

## Closed blockers

* CONTRACT-GAP-001 (closed 2026-09-04 by PR-M1.4a-FOLLOWUP / PR #57; the conductor/ledger layer
  inversion is removed — `conductor.contracts` and `ledger.catalog` import the pure-stdlib
  `blackbread.scope.canonical` leaf, and importing a proposal contract pulls 0 graph modules. The
  residual graph-internal copies are tracked as CONTRACT-GAP-002 (open). See GAP-REGISTER.md for full
  closure evidence.)
* GOV-GAP-001 (live ruleset conformance verified against the machine contract on 2026-08-31 —
  `ci-ok` and `GitGuardian Security Checks` are required in `main-branch-protection`, plus the
  documented solo-developer pull-request controls; see GAP-REGISTER.md for the captured snapshot).
* GRAPH-GAP-001 (closed 2026-09-02; durable temporal publication + cold-rebuild proofs + v1 guard
  reword; see GAP-REGISTER.md for full closure evidence).
* GRAPH-GAP-002 (closed 2026-09-02; cold-reconstruction stable-root verification + real cross-tenant
  isolation proof; released in PR #52; see GAP-REGISTER.md).

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
