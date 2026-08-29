# BlackBread Gap Register

This register contains cross-cutting blockers that cannot be closed by source changes alone. Capability
admission blockers are recorded with their owner, milestone, and release in
`config/capability-registry.json`.

## GOV-GAP-001 — AI review policy and live main ruleset are not aligned

- **Status:** OPEN
- **Severity:** P0 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** R0 and every real-target release
- **Current evidence:** two rulesets enforce main-branch protection, but AI review enforcement is
  transitioning to the repository-owned `ai-review-gate`:
  - Ruleset `main-branch-protection` (`21644438`): deletion, non-fast-forward, required linear
    history, pull_request (0 approving reviews, stale-review dismissal, review-thread resolution
    required), required_status_checks (`quality`, `tests`, `security`, `governance`,
    `Sourcery review`) with strict branch-currency policy. No bypass actors. The live ruleset does
    not yet require repository-owned `ai-review-gate`; Sourcery produced quota-driven `skipped`
    evidence on PR #13 and is advisory in the intended policy.
  - Ruleset `main-approval-required` (`21698082`): pull_request (1 approving review). Bypass actor:
    ChatGPT/Codex integration (`actor_id: 1144995`, `bypass_mode: pull_request`).
  - The split ensures Codex can bypass the human-approval requirement but CANNOT bypass status
    checks, thread resolution, deletion, non-fast-forward, or linear history.
- **Required closure:** accepted ADR, repository rules, machine contract, governance tests, actual
  Qodo and CodeRabbit evidence semantics, and the live ruleset must agree on `ai-review-gate`.
- **Verification:** PR #13 observed Qodo review actor `qodo-code-review[bot]` (user ID 151058649,
  app slug `qodo-code-review`) bound to head `aca9606cc6842c1282cb5c182efaef82fb6b2e64`
  through review `commit_id`. A manually triggered CodeRabbit FULL review covered the same head but
  no sufficiently verified machine-readable CodeRabbit current-head schema is yet encoded. Re-read
  the live ruleset and exercise `ai-review-gate` on a new head before closure.
- **Compensating control:** fail closed. Safety-critical changes remain ineligible until independent
  CodeRabbit evidence can be verified deterministically; no automatic degraded mode is approved.

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
