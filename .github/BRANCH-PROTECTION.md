# Main Branch Protection Contract

The repository ruleset for `main` must enforce all of the following:

- Pull request required with at least one approval.
- Code Owner review required.
- Stale approvals dismissed on new commits.
- All review threads resolved.
- Linear history; branch deletion and non-fast-forward updates blocked.
- No bypass actors, including administrators and automation agents.
- The branch must be current before merge.
- Required CI status checks: `quality`, `tests`, `security`, and `governance`.

The workflow alone does not make checks blocking. Repository ruleset configuration is release evidence.
Until the four status checks and Code Owner review are visible in the active ruleset, `GOV-GAP-001`
blocks R0 and every later release.
