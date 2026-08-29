# AI Review Integration Evidence

Repository configuration cannot guarantee that a third-party SaaS reviewer runs. PR #13 installs
`ai-review-gate` as bootstrap infrastructure; it is not yet a live required check. After merge,
protected `main` must own the workflow and evaluator before they can decide merge eligibility from
native GitHub evidence. The mandatory `quality`, `tests`, `security`, and `governance` jobs remain
independent requirements.

## Qodo: primary automated reviewer

PR #13 established the observed trusted identity and two accepted evidence shapes. Qodo evidence is
valid when either:

1. Qodo emits a trusted native `PullRequestReview` in submitted state `COMMENTED`, with its
   `commit_id` equal to the current PR head; or
2. Qodo emits the narrow authenticated provider-specific machine evidence observed live: an issue
   comment from the trusted bot and GitHub App containing exactly one
   `by qodo was updated up to the latest commit` marker whose full repository-bound commit URL
   equals the current PR head.

The trusted identity fields are:

- bot login: `qodo-code-review[bot]`;
- bot user ID: `151058649`;
- bot user type: `Bot`;
- GitHub App ID: `484649`;
- GitHub App slug: `qodo-code-review`;
- actionable findings: native GitHub review threads, whose resolution is independently required by
  protected-main branch rules.

Qodo did not publish a check run or commit status on the observed head. Do not invent or require a
raw Qodo status context. Vendor prose is untrusted: the gate does not parse summaries, bug counts,
rule-violation counts, skill-insight counts, recommendations, or arbitrary issue-comment text. It
recognizes only the authenticated current-head issue-comment marker above as provider-specific
machine evidence; owner/user-authored copies do not qualify. Missing, wrong-identity, stale,
wrong-head, incomplete, or unreadable evidence fails closed. Actionable findings remain governed by
native review threads and protected-main thread resolution. Qodo had to be triggered on the
already-open PR #13, so automatic review must not be assumed.

`.pr_agent.toml` predates the observed modern app identity. Its authority or compatibility with the
installed app has not been verified; treat it as a candidate configuration pending live evidence.
Selecting Qodo as primary is an engineering-policy decision based on the required review model, not a
claim of vendor superiority, and must be reevaluated using real BlackBread PR evidence.

## CodeRabbit: independent reviewer

`.coderabbit.yaml` contains repository review guidance, but configuration does not prove service
execution. PR #13 required a manually triggered FULL review. For safety-critical changes, explicitly
trigger a FULL review when automatic review did not run. The review must cover the exact current head
and all actionable findings must be resolved or receive evidence-backed disposition.

The observed CodeRabbit result reported no actionable comments. Its separate docstring-coverage
warning was not an actionable inline review thread and does not create a repository requirement.
Current-head CodeRabbit evidence is not yet encoded because a sufficiently verified machine-readable
identity and schema have not been observed. Safety-critical evaluation therefore fails closed.

## Sourcery and other reviewers

Sourcery is advisory during the transition. On PR #13 its review concluded `skipped` because of quota
exhaustion; `skipped` is not successful review evidence. Sourcery is not uninstalled or configured by
this change and does not replace Qodo, CodeRabbit, or first-party CI.

Codex, Bito, and other reviewers provide additional evidence only when actually present. They do not
silently substitute for Qodo or the required independent CodeRabbit review.

## Repository-owned policy and bootstrap

Normal changes require a trusted completed Qodo review for the current head and zero unresolved
Qodo-authored review threads. Safety-critical paths additionally require verified current-head
CodeRabbit FULL-review evidence. No automatic degraded mode is approved; outages, quota exhaustion,
timeouts, missing evidence, and policy evaluation errors fail closed.

The workflow uses supported `pull_request_target`, `pull_request_review`, and `issue_comment`
triggers and checks out protected `main`, never candidate PR code. An issue-comment create/edit event
is only a PR-scoped wake-up signal: the trusted evaluator ignores event comment content and re-fetches
the PR head and evidence through GitHub APIs before re-verifying the head. PR #13 cannot run this
trusted boundary because `main` does not yet contain it. After PR #13 merges, a separate activation PR
must demonstrate the exact `ai-review-gate` context and fail-closed behavior. Only then may the live
ruleset require the gate.
