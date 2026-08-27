# BlackBread Gap Register

This register contains cross-cutting blockers that cannot be closed by source changes alone. Capability
admission blockers are recorded with their owner, milestone, and release in
`config/capability-registry.json`.

## GOV-GAP-001 — Main ruleset lacks required checks and the approved agent bypass

- **Status:** OPEN
- **Severity:** P0 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** R0 and every real-target release
- **Current evidence:** ruleset `main-branch-protection` (`21644438`) is active with no bypass actors,
  one required approval, stale-review dismissal, review-thread resolution, linear history, deletion
  protection, and non-fast-forward protection. It does not require Code Owner review, an up-to-date
  branch, any status check, or the approved automation actor.
- **Required closure:** require the `quality`, `tests`, `security`, and `governance` checks from
  `.github/workflows/ci.yml`; require Code Owner review and an up-to-date branch on the default path;
  and add only the approved ChatGPT/Codex GitHub integration or dedicated automation account to the
  bypass list when direct delivery is required.
- **Verification:** re-read the active ruleset through the GitHub API and attach the response, including
  required checks and the exact bypass actor, to the milestone conformance record.
- **Compensating control:** none. Do not claim R0, use direct agent delivery, or merge release-bearing
  work until the server-side configuration is verified. Governance-only work may merge to close this gap.
