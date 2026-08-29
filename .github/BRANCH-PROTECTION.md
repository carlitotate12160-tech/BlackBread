# Main Branch Protection Contract

The machine-readable contract is `.github/agent-delivery.json`. The repository ruleset for `main`
must enforce the following default path:

- Pull request required.
- **One human Code Owner approval is required.** `CODEOWNERS` names the repository owner as the sole
  Code Owner. The owner must manually review and approve every change; GitHub does not permit a
  pull-request author to self-approve, so the owner may not author the final merge commit they also
  approve. The final merge is performed manually by the repository owner.
- Stale approvals are dismissed on new commits.
- `require_last_push_approval` is enabled.
- All review threads resolved and no `changes requested` review remaining.
- The branch must be current before merge.
- **No ruleset bypass actors.** Automation integrations may create commits, push a feature branch,
  and update a pull request, but they may not bypass the approval, status-check, or thread-resolution
  gates, and they may not click the merge button. The repository owner is the only merge authority.
- **Required status checks** (source-pinned):
  - `quality` — GitHub Actions, App ID 15368
  - `tests` — GitHub Actions, App ID 15368
  - `security` — GitHub Actions, App ID 15368
  - `governance` — GitHub Actions, App ID 15368
  - `GitGuardian Security Checks` — GitGuardian, App ID 46505
- **Required code scanning results:** CodeQL, security alerts `high_or_higher`, tool/analysis alerts
  `errors`.
- **Require code quality results:** OFF. BlackBread currently enforces code quality through the
  `quality` CI job (Ruff lint, Ruff format, mypy, McCabe complexity); GitHub Code Quality is not yet
  activated.
- **AI review:** Qodo review on the exact current head and CodeRabbit FULL review for safety-critical
  changes are mandatory parts of the review process, and every actionable AI-bot comment must be
  dispositioned before a human Code Owner approval is given. The repository-owned `ai-review-gate`
  is `bootstrap_not_enforced` and does not replace any first-party CI check. It is not a required
  status check until `GOV-GAP-001` through `GOV-GAP-005` are closed.
- Linear history; branch deletion, force-push, direct push to `main`, and non-fast-forward updates
  are blocked.

The legacy ruleset `main-approval-required` is kept in `evaluate` mode only as rollback evidence. It
must not provide an active bypass path. `GOV-GAP-001` remains open until the `ai-review-gate` is
owned by protected `main`, exercised by a later activation PR, and the live ruleset is then updated
while retaining the four mandatory first-party CI checks, `GitGuardian Security Checks`, branch
currency, and the human Code Owner approval gate.

A governance-only change may merge when it closes a recorded governance blocker and there is no
remaining blocking debt for the requested milestone or release. If GitHub denies an operation, the
agent must stop and report the exact server-side constraint.
