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
  the live ruleset and exercise `ai-review-gate` on a new head before closure. PR #13 only installs
  bootstrap infrastructure: its candidate evaluator is not trusted authority and cannot validate
  this PR. Protected `main` must own the evaluator before an activation PR can exercise it.
- **Compensating control:** fail closed. Safety-critical changes remain ineligible until independent
  CodeRabbit evidence can be verified deterministically; no automatic degraded mode is approved.

## GOV-GAP-002 — ai-review-gate issue_comment check SHA targeting

- **Status:** OPEN
- **Severity:** P1 governance
- **Owner:** repository administrator
- **Target milestone:** ai-review-gate activation
- **Blocks:** ai-review-gate activation as required status check
- **Current evidence:** GitHub `issue_comment` workflows use the last commit on the default branch as
  `GITHUB_SHA`, not the PR head. The automatic Actions job check from `issue_comment` events is
  therefore attached to the wrong SHA and cannot serve as the required `ai-review-gate` context for
  branch protection. PR #13 adds `issue_comment` triggers as wake-up signals but does not implement
  an explicit commit-status publisher that targets the verified PR head SHA. This is acceptable for
  the bootstrap phase because `ai-review-gate` is `bootstrap_not_enforced` and no live ruleset
  consumes it yet.
- **Required closure:** implement a repository-owned status publisher using the GitHub commit-status
  API (`POST /repos/{repository}/statuses/{verified_head_sha}`) with context `ai-review-gate`,
  publishing `pending` before evaluation and `success` or `failure` after, always targeting the
  authoritative PR head SHA from `GitHubEvidenceReader`. Handle head races, API exceptions, and
  bounded descriptions. Rename the Actions job to `ai-review-gate-controller` so its automatic check
  is not confused with the required gate context. Add `statuses: write` permission. Prove with
  governance tests that the target SHA comes from the authoritative PR API, never from event
  `GITHUB_SHA` or candidate-controlled input.
- **Verification:** a separate activation PR must demonstrate the exact `ai-review-gate` status
  context published against the correct PR head SHA, with fail-closed behavior for missing evidence,
  head races, and API exceptions.
- **Compensating control:** `ai-review-gate` is not a required status check. The four mandatory
  first-party CI checks (`quality`, `tests`, `security`, `governance`) remain required. No merge
  depends on `ai-review-gate` until GOV-GAP-002 is closed and GOV-GAP-001 is closed.

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
