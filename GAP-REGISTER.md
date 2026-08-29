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
- **Current evidence:** the live ruleset is consolidated into a single `main-branch-protection`
  (`21644438`) that requires deletion, non-fast-forward, required linear history, pull_request with
  zero approving reviews (solo-developer mode: `require_code_owner_review: false`,
  `require_last_push_approval: false`, `require_extra_approval_for_unattributed_changes: false`),
  review-thread resolution, source-pinned required_status_checks (`quality`, `tests`, `security`,
  `governance`, `GitGuardian Security Checks`), CodeQL code scanning (`high_or_higher` security
  alerts and `errors` tool/analysis alerts), and strict branch currency. The legacy
  `main-approval-required` ruleset (`21698082`) is disabled and retained only as rollback evidence;
  it has no enforcement effect and provides no active bypass. `ai-review-gate` remains
  `bootstrap_not_enforced` and is not a required status check until `GOV-GAP-001` through
  `GOV-GAP-005` are closed.
- **Required closure:** accepted ADR, repository rules, machine contract, governance tests, live
  source-pinned status checks (including `GitGuardian Security Checks`), CodeQL code scanning,
  review-thread resolution, actual Qodo and CodeRabbit evidence semantics, and the live ruleset must
  agree on `ai-review-gate`.
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
- **Current evidence:** the activation implementation PR adds a `StatusPublisher` that publishes
  commit-status `pending`/`success`/`failure` to the authoritative PR head SHA via
  `POST /repos/{repository}/statuses/{verified_head_sha}` with context `ai-review-gate`. The workflow
  job is renamed to `ai-review-gate-controller` and `statuses: write` is added. The SHA target comes
  exclusively from `GitHubEvidenceReader.fetch_head_sha()` which calls the GitHub PR API. Head races
  publish `failure` to the original head and never `success`. Exceptions after head capture attempt
  `failure` to the known head. Implementation exists but protected-main live activation proof is still
  pending.
- **Required closure:** a separate live-activation PR must demonstrate the exact `ai-review-gate`
  status context published against the correct PR head SHA from protected `main`, with fail-closed
  behavior for missing evidence, head races, and API exceptions. Then update the live ruleset to
  require `ai-review-gate` and verify.
- **Verification:** the live-activation PR exercises the controller from protected `main` and proves
  the status appears on the correct PR head SHA with the correct context.
- **Compensating control:** `ai-review-gate` is not a required status check. The four mandatory
  first-party CI checks (`quality`, `tests`, `security`, `governance`) remain required. No merge
  depends on `ai-review-gate` until GOV-GAP-002 is closed and GOV-GAP-001 is closed.

## GOV-GAP-003 — ai-review-gate does not verify review-thread resolution

- **Status:** OPEN
- **Severity:** P1 governance
- **Owner:** repository administrator
- **Target milestone:** ai-review-gate activation
- **Blocks:** ai-review-gate activation as a required status check
- **Current evidence:** the activation implementation PR adds GraphQL `reviewThreads` fetching with
  bounded pagination to `GitHubEvidenceReader.read()` and passes `review_threads` to `evaluate()`.
  The gate denies eligibility while any PR review thread is unresolved, regardless of thread author.
  API failures, malformed responses, and pagination overflow fail closed. Implementation exists but
  protected-main live activation proof is still pending.
- **Required closure:** a separate live-activation PR must demonstrate that a current-head Qodo review
  with an unresolved thread is rejected and the same review with every thread resolved is accepted,
  from protected `main`. Close together with GOV-GAP-001 and GOV-GAP-002 before activation.
- **Verification:** the live-activation PR demonstrates thread enforcement against real GitHub
  review-thread state.
- **Compensating control:** the live `main-branch-protection` ruleset (`21644438`) independently
  requires review-thread resolution for every conversation, so an unresolved thread blocks merge
  today, and `ai-review-gate` is `bootstrap_not_enforced`. No merge depends on this gate until
  GOV-GAP-001, GOV-GAP-002, and GOV-GAP-003 are closed.

## GOV-GAP-004 — ai-review-gate controller lacks concurrency ordering

- **Status:** OPEN
- **Severity:** P2 governance
- **Owner:** repository administrator
- **Target milestone:** ai-review-gate activation
- **Blocks:** ai-review-gate activation as a required status check
- **Current evidence:** the workflow has no `concurrency` group. Multiple
  `pull_request_target`, `pull_request_review`, and `issue_comment` events can
  trigger overlapping controller runs for the same unchanged head. An older run
  that finishes last can overwrite a newer failure with success after evidence
  was removed or a thread became unresolved. The SHA comparison only detects
  commit changes, not changing review/thread evidence on the same SHA.
- **Required closure:** add a `concurrency` group keyed by PR number with
  `cancel-in-progress: false`, or implement timestamp-based status ordering so
  older runs cannot overwrite newer decisions. Prove with governance tests.
  Close together with GOV-GAP-001, GOV-GAP-002, and GOV-GAP-003 before
  activation.
- **Verification:** the live-activation PR demonstrates that overlapping runs
  do not produce conflicting status outcomes.
- **Compensating control:** `ai-review-gate` is `bootstrap_not_enforced`. The
  four mandatory first-party CI checks remain required. No merge depends on
  this gate until all GOV gaps are closed.

## GOV-GAP-005 — review-thread resolution changes lack wake-up trigger

- **Status:** OPEN
- **Severity:** P1 governance
- **Owner:** repository administrator
- **Target milestone:** ai-review-gate activation
- **Blocks:** ai-review-gate activation as a required status check
- **Current evidence:** the workflow listens to `pull_request_target`,
  `pull_request_review`, and `issue_comment` triggers. GitHub has no native
  webhook for review-thread resolution changes. Resolving or unresolving a
  thread does not trigger any configured event. Consequently, resolving the
  last outstanding thread leaves a previously published failure in place
  indefinitely, and creating/reopening a thread after success leaves a stale
  success until some unrelated event runs the controller.
- **Required closure:** add a reliable wake-up path for thread-resolution
  changes (scheduled reconciliation, GitHub webhook subscription, or another
  bounded mechanism). Prove that thread resolution changes trigger
  re-evaluation. Close together with GOV-GAP-001 through GOV-GAP-004 before
  activation.
- **Verification:** the live-activation PR demonstrates that resolving a
  thread triggers re-evaluation and status update.
- **Compensating control:** `ai-review-gate` is `bootstrap_not_enforced`.
  The live `main-branch-protection` ruleset (`21644438`) independently
  requires review-thread resolution for every conversation. No merge depends
  on this gate until all GOV gaps are closed.

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
