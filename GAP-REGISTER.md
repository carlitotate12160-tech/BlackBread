# BlackBread Gap Register

This register contains cross-cutting blockers that cannot be closed by source changes alone. Capability
admission blockers are recorded with their owner, milestone, and release in
`config/capability-registry.json`.

## GOV-GAP-001 — Live main ruleset is not verified against the machine contract

- **Status:** OPEN
- **Severity:** P0 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** R0 and every real-target release
- **Current evidence:** the live ruleset is consolidated into a single `main-branch-protection`
  (`21644438`) that is expected to require deletion protection, non-fast-forward, required linear
  history, pull_request with zero approving reviews (solo-developer mode:
  `require_code_owner_review: false`, `require_last_push_approval: false`,
  `require_extra_approval_for_unattributed_changes: false`), review-thread resolution, source-pinned
  required_status_checks (`ci-ok` aggregator, `GitGuardian Security Checks`), CodeQL code scanning
  (`high_or_higher` security alerts and `errors` tool/analysis alerts), and strict branch currency.
  The legacy `main-approval-required` ruleset (`21698082`) is disabled and retained only as rollback
  evidence; it has no enforcement effect and provides no active bypass. Whether the live GitHub
  ruleset actually matches `.github/agent-delivery.json` and `.github/BRANCH-PROTECTION.md` cannot
  be proven from source and is not yet independently verified.
- **Required closure:** read the live `main-branch-protection` ruleset from GitHub and confirm it
  matches the machine contract and prose exactly — the `ci-ok` aggregator check, `GitGuardian
  Security Checks`, CodeQL code scanning, review-thread resolution, branch currency, and the
  solo-developer zero-approval policy — with no unexpected required check, bypass actor, or missing
  control. Record the verified ruleset snapshot.
- **Verification:** a captured live ruleset read that matches the machine contract, referenced from
  the R0 conformance record.
- **Compensating control:** fail closed. The `ci-ok` aggregator (which depends on `quality`,
  `tests`, `security`, and `governance`), `GitGuardian Security Checks`, and review-thread
  resolution are required by the machine contract; no target-facing release proceeds while ruleset
  conformance is unverified.

## GOV-GAP-002 through GOV-GAP-005 — ai-review-gate activation (WITHDRAWN)

- **Status:** CLOSED (WITHDRAWN 2026-08-30)
- **Owner:** repository administrator
- **Superseded by:** removal of the repository-owned `ai-review-gate` apparatus.
- **Resolution:** the repository-owned `ai-review-gate` workflow, its evaluator
  (`src/blackbread/governance/ai_review_gate.py`), and `docs/AI-REVIEW-SETUP.md` were removed. For a
  solo-developer repository the gate enforced nothing — it was `bootstrap_not_enforced` and never a
  required status check — while producing a persistent failing check on every pull request and
  cascading `issue_comment` runs. The four sub-gaps it tracked are moot once the gate no longer
  exists: issue_comment SHA targeting (former GOV-GAP-002), review-thread resolution inside the gate
  (former GOV-GAP-003), controller concurrency ordering (former GOV-GAP-004), and thread-resolution
  wake-up (former GOV-GAP-005). Qodo and CodeRabbit remain active advisory reviewers whose actionable
  comments must be dispositioned before merge; enforcement relies on first-party CI (`quality`,
  `tests`, `security`, `governance`), `GitGuardian Security Checks`, and protected-main review-thread
  resolution.
- **Verification:**
  `tests/governance/test_governance_contract.py::test_ai_review_gate_apparatus_is_fully_removed`.

## LEDGER-GAP-001 — R0 trust-spine integration remains incomplete

- **Status:** OPEN
- **Severity:** P0 architecture
- **Owner:** trust-spine
- **Target milestone:** M1
- **Blocks:** R0 and every target-facing release
- **Current evidence:** the tenant-bound, hash-versioned PostgreSQL ledger supports serialized append,
  replay verification, immutable envelope hashing, and database-level UPDATE/DELETE/TRUNCATE denial.
  Graph projection, NetworkX rebuild, Conductor, Policy Kernel v1, execution leases, dual kill-switch,
  and authenticated PostgreSQL row-level tenant context are not implemented.
- **Required closure:** wire every trust-spine publisher through the ledger; implement projector/rebuild,
  deterministic Conductor and Policy Kernel paths, lease and kill-switch enforcement, and database-role
  tenant isolation; prove replay and negative scope/lease paths end to end.
- **Verification:** `tests/ledger/` plus future trust-spine integration suites and the versioned R0
  conformance record.
- **Compensating control:** none. The ledger slice may merge, but R0/M1 and target-facing execution
  remain blocked until closure evidence is attached.
