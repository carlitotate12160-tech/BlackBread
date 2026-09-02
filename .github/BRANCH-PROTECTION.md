# Main Branch Protection Contract

The machine-readable contract is `.github/agent-delivery.json`. The repository ruleset for `main`
must enforce the following default path:

- Pull request required.
- **Solo-developer mode: zero approving reviews required.** `CODEOWNERS` names the repository owner
  and `@speedup12160-spec` as Code Owners, but Code Owner review is not enforced and
  `require_last_push_approval` is disabled. The pull-request author may merge without a second
  approving review. `require_extra_approval_for_unattributed_changes` is disabled.
- Stale approvals are dismissed on new commits.
- All review threads resolved and no `changes requested` review remaining.
- The branch must be current before merge.
- **No active ruleset bypass actors.** Automation integrations may create commits, push a feature branch,
  and update a pull request, but they may not bypass the approval, status-check, or thread-resolution
  gates, and they may not click the merge button. The repository owner is the only merge authority.
- **Required status checks** (source-pinned):
  - `ci-ok` — GitHub Actions aggregator job (depends on `quality`, `tests`, `security`, `governance`)
  - `GitGuardian Security Checks` — GitGuardian, App ID 46505
- **Required code scanning results:** CodeQL, security alerts `high_or_higher`, tool/analysis alerts
  `errors`.
- **Require code quality results:** OFF. BlackBread currently enforces code quality through the
  `quality` CI job (Ruff lint, Ruff format, mypy, McCabe complexity); GitHub Code Quality is not yet
  activated.
- **AI review:** PR-Agent (CodiumAI) is auto-triggered via `.github/workflows/pr-agent.yml` on
  non-draft PRs (opened, reopened, ready_for_review) using a DeepSeek API key. Per ADR-FINAL-002
  Amendments A-001 and A-002, PR-Agent uses `deepseek/deepseek-v4-pro` when canonical changed-path
  classification requires binding review and the exact `safety-critical` label is present; lookup or
  label mismatches fail closed. Other PRs use `deepseek/deepseek-v4-flash` for advisory review.
  For **safety-critical** PRs, the current-head PR-Agent review is binding and must be complete
  with all actionable findings disposed before merge; the owner triggers it via `/review` comment
  at the final head. For **non-safety-critical** PRs, CodeRabbit is the primary advisory reviewer,
  auto-triggered via `coderabbit-trigger.yml` (PAT-owned comment). If CodeRabbit is rate-limited or
  unavailable, PR-Agent may provide fallback advisory review; if neither is available, the owner
  dispositions the absence explicitly in the PR. Every actionable AI-bot comment must be
  dispositioned before merge. Neither AI reviewer is a required status check; the mandatory first-party CI gate is `ci-ok`
  (aggregating `quality`, `tests`, `security`, `governance`) plus `GitGuardian Security Checks`,
  review-thread resolution, and branch currency.
- Linear history; branch deletion, force-push, direct push to `main`, and non-fast-forward updates
  are blocked.

The legacy ruleset `main-approval-required` is disabled as rollback evidence. Its inactive
configuration does not provide a bypass path. `GOV-GAP-001` is CLOSED as of 2026-08-31 after the live
`main-branch-protection` ruleset was verified on GitHub to match this contract: the `ci-ok`
aggregator check, `GitGuardian Security Checks`, CodeQL code scanning, branch currency, review-thread
resolution, squash-only merge, stale-review dismissal, no bypass actors, and the solo-developer
zero-approval policy. See GAP-REGISTER.md for the captured snapshot.

A governance-only change may merge when it closes a recorded governance blocker and there is no
remaining blocking debt for the requested milestone or release. If GitHub denies an operation, the
agent must stop and report the exact server-side constraint.

## Solo-developer configuration

This repository operates in solo-developer mode. The live `main-branch-protection` ruleset
(`21644438`) enforces `required_approving_review_count: 0`,
`require_code_owner_review: false`, `require_last_push_approval: false`,
`require_extra_approval_for_unattributed_changes: false`, `dismiss_stale_reviews_on_push: true`,
`require_review_thread_resolution: true`, and `allowed_merge_methods: ["squash"]`. The
`CODEOWNERS` file is retained for reviewer auto-assignment but does not block merge.
