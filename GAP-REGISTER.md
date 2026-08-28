# BlackBread Gap Register

This register contains cross-cutting blockers that cannot be closed by source changes alone. Capability
admission blockers are recorded with their owner, milestone, and release in
`config/capability-registry.json`.

## GOV-GAP-001 — Main ruleset lacks required checks and branch currency

- **Status:** CLOSED
- **Severity:** P0 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** R0 and every real-target release
- **Current evidence:** two rulesets now enforce main-branch protection:
  - Ruleset `main-branch-protection` (`21644438`): deletion, non-fast-forward, required linear
    history, pull_request (0 approving reviews, stale-review dismissal, review-thread resolution
    required), required_status_checks (`quality`, `tests`, `security`, `governance`) with strict
    branch-currency policy. No bypass actors.
  - Ruleset `main-approval-required` (`21698082`): pull_request (1 approving review). Bypass actor:
    ChatGPT/Codex integration (`actor_id: 1144995`, `bypass_mode: pull_request`).
  - The split ensures Codex can bypass the human-approval requirement but CANNOT bypass status
    checks, thread resolution, deletion, non-fast-forward, or linear history.
- **Required closure:** satisfied — required checks and branch currency are enforced.
- **Verification:** re-read both rulesets through the GitHub API on 2026-08-28; confirmed
  `required_status_checks` and `strict_required_status_checks_policy: true` in ruleset 21644438
  with no bypass actors, and Codex bypass limited to ruleset 21698082 (approval only).
- **Compensating control:** none needed — server-side configuration verified.
