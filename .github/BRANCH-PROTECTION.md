# Main Branch Protection Contract

The repository ruleset for `main` must enforce the following default path:

- Pull request required with at least one approval.
- Code Owner review required.
- Stale approvals dismissed on new commits.
- All review threads resolved.
- The branch must be current before merge.
- Required CI status checks: `quality`, `tests`, `security`, and `governance`.
- Linear history; branch deletion, force-push, and non-fast-forward updates blocked.

## Approved automation bypass

The repository owner may configure one least-privilege bypass actor for the ChatGPT/Codex GitHub
automation used for this repository. Prefer the exact GitHub App/integration or a dedicated bot account;
do not grant a blanket bypass to all writers or all administrators when a specific actor is available.

That actor may commit, push, update a pull request, and merge without repeated confirmation after the
owner requests repository work. An `Always allow` ruleset bypass may be used when direct-to-`main`
delivery is required, but it does not waive the repository's internal delivery gates:

- validate the complete changed tree;
- use a fast-forward ref update and an expected head SHA;
- require green applicable checks for that SHA;
- require no unresolved `request changes` review or applicable review thread;
- require no blocking debt for the requested milestone or release;
- never rewrite history, force-push, delete the protected branch, or suppress evidence.

A governance-only change may merge when it closes a recorded governance blocker. If GitHub denies an
operation, the agent must stop and report the exact server-side constraint.

The workflow alone does not make checks blocking, and repository prose cannot configure a GitHub
ruleset. The active ruleset response is release evidence. Until the four checks, Code Owner requirement,
up-to-date requirement, and approved automation bypass are visible in ruleset `21644438`,
`GOV-GAP-001` blocks R0 and every later release.
