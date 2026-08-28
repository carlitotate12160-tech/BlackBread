# BlackBread Gap Register

This register contains cross-cutting blockers that cannot be closed by source changes alone. Capability
admission blockers are recorded with their owner, milestone, and release in
`config/capability-registry.json`.

## GOV-GAP-001 — Main ruleset lacks required checks and branch currency

- **Status:** OPEN
- **Severity:** P0 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** R0 and every real-target release
- **Current evidence:** ruleset `main-branch-protection` (`21644438`) is active with the specific
  ChatGPT/Codex integration (`actor_id: 1144995`) as its only always-bypass actor, one required
  approval, stale-review dismissal, review-thread resolution, linear history, deletion protection,
  and non-fast-forward protection. It does not require an up-to-date branch or any status check.
- **Required closure:** require the `quality`, `tests`, `security`, and `governance` checks from
  `.github/workflows/ci.yml` and require the pull-request branch to be current. Retain only the named
  integration bypass and apply `.github/agent-delivery.json` so the bypass cannot waive substantive
  delivery gates.
- **Verification:** re-read the active ruleset through the GitHub API and attach the response, including
  required checks, branch-currency policy, and the exact bypass actor, to the milestone conformance
  record.
- **Compensating control:** none for a release. Do not claim R0 or merge release-bearing work until the
  server-side configuration is verified. Governance-only work may merge to close this gap.
