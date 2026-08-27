# BlackBread Gap Register

This register contains cross-cutting blockers that cannot be closed by source changes alone. Capability
admission blockers are recorded with their owner, milestone, and release in
`config/capability-registry.json`.

## GOV-GAP-001 — Required CI checks are not in the active main ruleset

- **Status:** OPEN
- **Severity:** P0 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** R0 and every real-target release
- **Current evidence:** ruleset `main-branch-protection` (`21644438`) is active with no bypass actors,
  one required approval, stale-review dismissal, review-thread resolution, linear history, deletion
  protection, and non-fast-forward protection. It does not require Code Owner review or any status check.
- **Required closure:** enable Code Owner review and require the `quality`, `tests`, `security`, and
  `governance` checks from `.github/workflows/ci.yml` with the branch required to be current.
- **Verification:** re-read the active ruleset through the GitHub API and attach the response to the
  milestone conformance record.
- **Compensating control:** none. Do not claim R0 or merge release-bearing work until closed.
