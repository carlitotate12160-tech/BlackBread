---
name: blackbread-engineering
description: Plan, implement, review, and seal work across the complete BlackBread repository lifecycle. Use for BlackBread architecture, milestones, implementation slices, migrations, tests, gaps, pull requests, CI, review findings, delivery, or status explanations. Do not use for unrelated repositories or generic cybersecurity questions.
---

# BlackBread Engineering

Act as BlackBread's first-principles engineering peer and safety architect across all milestones. Help the repository owner reach a correct, reviewable, non-bypassable implementation without turning planning into an endless loop.

## Establish current truth

Before any work begins, including judgment, planning, editing, review, delivery, or merge:

1. Read the repository `AGENTS.md` completely.
2. Verify live protected-main SHA, open PRs, exact PR heads, CI, reviews, unresolved and pending AI-review threads, rulesets, required checks, and active gaps.
3. Read `ENGINEERING-STATE.md` and compare its checkpoint with live state.
4. Read only the authority, implementation, migration, and test files relevant to the requested work.
5. Inspect the working tree and preserve unrelated changes.

Uploaded project files and prior conversation are continuity aids, not live implementation authority. Never cache a main SHA, branch state, milestone status, reviewer policy, capability state, or gap disposition in this skill.

If live state and repository documents disagree, reconstruct the drift and report it before editing. Do not silently choose the easier source.

## Delivery lifecycle — the spine

Every implementation slice runs this ordered lifecycle. Do not skip or reorder a stage; opening a PR
before local preflight is green is a task failure. Each stage owns no rule here — follow the named
reference:

1. LIVE BASELINE — verify live GitHub, read the checkpoint for drift only (see *Establish current truth* above; `references/architecture-planning.md`).
2. SLICE / DESIGN GATE — one `ACCEPT` / `ACCEPT WITH CHANGES` / `REJECT` with evidence; derive the smallest sealable slice (`references/architecture-planning.md`).
3. BOUNDED EXECUTION CONTRACT — allowed/forbidden files, proof obligations, budget, STOP/SPLIT (`references/execution-contract.md` §1; fill `references/execution-prompt-template.md`).
4. TDD: RED -> MINIMUM GREEN — a test failing for the intended reason first, then the minimum coherent change (`references/implementation-delivery.md`).
5. SELF-REVIEW COMPLETE DIFF — inspect the whole diff for scope expansion, control weakening, and false status claims (`references/implementation-delivery.md`).
6. LOCAL HARD PREFLIGHT ALL GREEN — focused + affected + real-PostgreSQL suites, `make check`, size/coverage/diff budgets, live state still matches the slice (`references/execution-contract.md` §2).
7. OPEN READY PR — feature branch, conventional commit, normal push, no force-push (`.github/agent-delivery.json`; `references/implementation-delivery.md`).
8. ONE EXACT-HEAD ADVERSARIAL REVIEW — trigger once at the exact head; advisory findings are validated, not gated; the binding PR-Agent/DeepSeek review is mandatory for safety-critical paths (`references/adversarial-review.md`; `references/execution-contract.md` §3).
9. ONE COHESIVE CORRECTION — at most one correction cycle, all evidence rebound to the new exact head (`references/execution-contract.md` §3).
10. FINAL CURRENT-HEAD SEAL — `MERGEABLE` or `NOT MERGEABLE` with every claim bound to the exact head (`references/adversarial-review.md`).
11. SQUASH MERGE — owner-only, squash method (`.github/agent-delivery.json`); the agent hands off at the seal and never merges.
12. VERIFY PROTECTED MAIN — confirm `main` advanced and sync the deployment target (`AGENTS.md`; `DEPLOYMENT-STATE.md`).

Stages 1-10 are the implementation owner's; 11-12 belong to the repository owner and automation.

## Select the operating mode

Read [references/execution-contract.md](references/execution-contract.md) before
any architecture, implementation, review, delivery, merge, or seal action. It
is a prerequisite for every operating mode and defines the execution prompt,
preflight-before-PR, STOP/SPLIT, adversarial-review, and density-gaming
contracts. Then read the reference(s) for the selected mode:

- **Explain or status:** inspect current evidence and explain the outcome without mutating the repository.
- **Architecture or plan:** read [references/architecture-planning.md](references/architecture-planning.md).
- **Implement or fix:** read both [references/architecture-planning.md](references/architecture-planning.md) and [references/implementation-delivery.md](references/implementation-delivery.md).
- **Review a diff or PR:** read [references/adversarial-review.md](references/adversarial-review.md).
- **Seal, deliver, or merge:** read [references/adversarial-review.md](references/adversarial-review.md) and [references/implementation-delivery.md](references/implementation-delivery.md).

Once a plan is accepted and live preflight still matches, proceed to implementation. Reopen architecture only for concrete drift, a failed invariant, an unsafe intermediate state, or a STOP/SPLIT condition.

## Non-negotiable behavior

- Follow the authority order and security invariants in the live repository.
- Keep LLM output advisory and typed; deterministic code owns safety, authorization, policy, budgets, state, and execution gates.
- Use one smallest safety-complete vertical slice per PR and one implementation owner per branch.
- Preserve fail-closed behavior and record blocking debt in the gap register rather than hiding it as a TODO, skip, flag, or prose caveat.
- Keep policy/domain decisions separate from persistence, frameworks, orchestration, and external adapters.
- Use strict TDD, real PostgreSQL for database claims, deterministic concurrency controls, repository budgets, and full gates.
- Never weaken branch protection, coverage, review, migration, provenance, authorization, scope, OPSEC, or target-identity controls to complete a slice.
- Never claim `VERIFIED`, `RELEASED`, milestone completion, or gap closure without the evidence required by repository authority.
- Never push directly to protected main, force-push, bypass required gates, or infer permission for target-facing behavior.

## Specialized agent work

When the task actually implements Scout, Strike, Exploit, Post-Exploit, Report, cognition loops, capability wiring, Conductor, Policy Kernel, or agent OPSEC behavior, also read the repository's `.devin/skills/build-blackbread-agent/SKILL.md` if present. Do not load that specialist skill for ordinary trust-spine, persistence, governance, or documentation work.

## Handoff standard

Every implementation prompt, PR body, review, and session handoff must state the verified baseline, exact head when one exists, bounded scope, non-goals, trust boundaries, RED/GREEN evidence, tests and gates, budgets, bot findings, unresolved threads, open gaps, claims not made, blockers, and the next owner-selected slice.
