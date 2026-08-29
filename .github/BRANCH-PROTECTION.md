# Main Branch Protection Contract

The machine-readable contract is `.github/agent-delivery.json`. The repository ruleset for `main`
must enforce the following default path:

- Pull request required. Required human approvals remain 0 while the repository has no independent
  write-access reviewer; this is deliberate, not an AI approval substitution. First-party CI, thread
  resolution, and the repository-owned `ai-review-gate` are the technical enforcement path. If an
  independent trusted human reviewer with write access is later added, human approval policy may be
  restored to >=1.
- Stale approvals dismissed on new commits.
- All review threads resolved and no `changes requested` review remaining.
- The branch must be current before merge.
- Required status checks during bootstrap: mandatory first-party CI `quality`, `tests`, `security`,
  and `governance`. The repository-owned `ai-review-gate` is pending activation and does not replace
  first-party CI.
- Linear history; branch deletion, force-push, direct push to `main`, and non-fast-forward updates
  blocked.

CODEOWNERS remains routing and ownership evidence. Because this is currently a sole-owner repository
and GitHub does not permit the pull-request author to self-approve, Code Owner review is not a
server-side merge requirement at M0. The authenticated repository-owner instruction is the human
authorization for agent delivery; the GitHub approval and AI-review gates remain independent evidence.

## Approved automation integration

The repository owner may configure only the specific ChatGPT/Codex GitHub integration used for this
repository as a ruleset bypass actor. Do not grant blanket bypass to writers or administrators.

The integration may create commits, push a feature branch, update a pull request, and perform the final
merge without repeated confirmation. Its bypass is transport authority only and may not waive any
entry in `.github/agent-delivery.json`. In particular, the agent must:

- validate the complete changed tree and expected head SHA;
- require all four mandatory first-party CI checks green for that SHA;
- evaluate and reply to every AI-bot comment, fixing valid findings;
- require every applicable review thread resolved;
- require no `changes requested` review;
- require the branch to be current and blocking debt to be zero for the requested milestone/release;
- never push directly to `main`, rewrite history, force-push, delete the protected branch, suppress
  evidence, or dismiss a valid review merely to merge.

A governance-only change may merge when it closes a recorded governance blocker. If GitHub denies an
operation, the agent must stop and report the exact server-side constraint.

The workflow alone does not make checks blocking, and repository prose cannot configure a GitHub
ruleset. PR #13 is a bootstrap change and cannot be certified by evaluator code it introduces.
`GOV-GAP-001` remains open until protected `main` owns the evaluator, a subsequent activation PR
exercises its exact check context and fail-closed behavior, and the live ruleset is then updated while
retaining all four first-party CI checks and branch currency.
