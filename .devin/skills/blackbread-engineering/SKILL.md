---
name: blackbread-engineering
description: Plan, architect, implement, adversarially review, deliver, and seal the ADR-governed BlackBread platform across its authorization trust spine, Policy Kernel, Conductor, OPSEC, evidence ledger and projections, campaign intelligence, Capability Gateway, agent cognition, execution isolation, milestones, gaps, tests, pull requests, and CI. Use only for BlackBread; do not use for unrelated repositories or generic cybersecurity work.
---

# BlackBread Engineering

Act as BlackBread's first-principles engineering peer and safety architect across all milestones.
Preserve its defining split: five bounded reasoning roles over evidence-backed state, deterministic
central safety, typed execution, and no path from model belief to target effect. Reach a correct,
reviewable, non-bypassable implementation without turning planning into an endless loop.

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
3. DESIGN SEAL + BOUNDED EXECUTION CONTRACT — seal the architecture once, then derive the implementation-only packet (`references/execution-contract.md` §1; fill `references/design-seal-template.md`, then `references/execution-prompt-template.md`).
4. TDD: RED -> MINIMUM GREEN — a test failing for the intended reason first, then the minimum coherent change (`references/implementation-delivery.md`).
5. SELF-REVIEW COMPLETE DIFF — inspect the whole diff for scope expansion, control weakening, and false status claims (`references/implementation-delivery.md`).
6. LOCAL HARD PREFLIGHT ALL GREEN — focused + affected suites, applicable real-PostgreSQL or other authoritative integration proofs, `make check`, size/coverage/diff budgets, and live-state re-verification (`references/execution-contract.md` §2; use `references/qualification-runbook-template.md` when qualification runs in another environment).
7. OPEN READY PR — feature branch, conventional commit, normal push, no force-push (`.github/agent-delivery.json`; `references/implementation-delivery.md`).
8. ONE EXACT-HEAD ADVERSARIAL REVIEW — allow configured automation to run once or use only the approved trigger defined by live repository authority; validate advisory findings instead of obeying them blindly; complete the current binding independent review required for safety-critical paths (`references/adversarial-review.md`; `references/execution-contract.md` §3).
9. ONE COHESIVE CORRECTION — at most one correction cycle from a delta-only correction packet, all evidence rebound to the new exact head (`references/execution-contract.md` §3; fill `references/correction-packet-template.md`).
10. FINAL CURRENT-HEAD SEAL — `MERGEABLE` or `NOT MERGEABLE` with every claim bound to the exact head (`references/adversarial-review.md`).
11. SQUASH MERGE — owner-only, squash method (`.github/agent-delivery.json`); the agent hands off at the seal and never merges.
12. VERIFY PROTECTED MAIN — confirm `main` advanced and sync the deployment target (`AGENTS.md`; `DEPLOYMENT-STATE.md`).

Work is role-separated even when one person operates every tool:

- the **design controller** owns stages 1-3 and emits `DESIGN_SEALED` or stops;
- the **implementation owner** owns stages 4-5, the local portion of stage 6, and stage 7;
- the **qualification runner** owns only environment-specific proofs delegated from stage 6;
- the **review/seal owner** owns stages 8-10 and must not silently patch the branch;
- the **repository owner and automation** own stages 11-12.

Read `references/workflow-loop.md` before creating or consuming any handoff packet. A role may reuse
its verified source snapshot during one unchanged-head run. Re-read only when a recorded blob/head
changes, required evidence is missing, or a STOP/SPLIT condition is reached. A later role still
performs the live checks required by `AGENTS.md`, but consumes the sealed decisions instead of
re-running architecture.

## Select the operating mode

Read [references/execution-contract.md](references/execution-contract.md) before
any architecture, implementation, review, delivery, merge, or seal action. It
is a prerequisite for every operating mode and defines the execution prompt,
preflight-before-PR, STOP/SPLIT, adversarial-review, and density-gaming
contracts. Then read the reference(s) for the selected mode:

- **Explain or status:** inspect current evidence and explain the outcome without mutating the repository.
- **Architecture or plan:** read [references/architecture-planning.md](references/architecture-planning.md) and emit [the design seal](references/design-seal-template.md).
- **Implement:** validate the supplied design seal and implementation packet, then read [references/implementation-delivery.md](references/implementation-delivery.md). Read architecture planning only if the seal is missing, drifted, or declares a design failure.
- **Fix:** validate the exact-head correction packet, then read [references/implementation-delivery.md](references/implementation-delivery.md). Do not reopen architecture for a bounded code defect.
- **Review a diff or PR:** read [references/adversarial-review.md](references/adversarial-review.md).
- **Seal, deliver, or merge:** read [references/adversarial-review.md](references/adversarial-review.md) and [references/implementation-delivery.md](references/implementation-delivery.md).

For `IMPLEMENT`, architecture planning is used only to validate the supplied design seal and detect
drift. Do not repeat its feasibility analysis when the seal is complete and its source snapshot still
matches. For `FIX`, use a delta-only correction packet; reopen design only for an explicit design
failure or STOP/SPLIT condition.

Once a plan is accepted and live preflight still matches, proceed to implementation. Reopen architecture only for concrete drift, a failed invariant, an unsafe intermediate state, or a STOP/SPLIT condition.

## Route the BlackBread architecture lenses

For architecture, implementation, fix, review, and seal work, read only the applicable lens files
below in addition to the operating-mode references. Read the complete selected lens before acting.

| Changed responsibility | Required lens |
| --- | --- |
| Scout, Strike, Exploit, Post-Exploit, Report, campaign reasoning, graph semantics, evidence, findings, target identity, authorization semantics, or target-effect classification | [references/red-team-architecture.md](references/red-team-architecture.md) |
| Policy Kernel, Conductor, OPSEC, approvals, budgets, locks, leases, scheduling, cancellation, halt, cleanup coordination, resume, or replay | [references/control-plane-architecture.md](references/control-plane-architecture.md) |
| Digests, result objects, serialization, cross-stage handoffs, persistence, ledger events, provenance, RLS, tenant isolation, producer identity, or replay authenticity | [references/trust-boundary-provenance.md](references/trust-boundary-provenance.md) |
| Capability Gateway, registry enforcement, adapters, rendered invocation, destination revalidation, egress, executor, target health, session/secret custody, supply chain, platform qualification, or cleanup execution | [references/execution-plane-architecture.md](references/execution-plane-architecture.md) |

Load multiple lenses when the slice crosses their concerns. If the lens pass reveals more than one
independently sealable trust boundary, split before producing an execution prompt. Do not load every
lens for ordinary governance, documentation, or status work.

The lenses are procedural interpretations, never cached architecture authority. Re-read the live
`ADR-FINAL-002.md`, `ADR-FINAL-003.md`, `PRD.md`, rules, gap register, and capability registry named
by the selected lens. A lens may strengthen the proof required for an accepted decision; it may not
invent a capability, change a milestone, or weaken live authority.

## Require design feasibility before execution

For any new or materially revised boundary, complete the BlackBread Architecture Feasibility Gate
in `references/architecture-planning.md` before filling the execution prompt. In particular, prove
information sufficiency, attempt adversarial construction and deserialization, map producer and
consumer reachability, and examine how the next consumer could misuse the artifact. Trust-boundary
proof precedes budget-based splitting.

After the gate passes and the live baseline remains valid, stop revising the plan cosmetically.
Reopen it only for concrete drift, a failed proof, a reproduced defect, unsafe reachability, or a
declared STOP/SPLIT condition.

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

When the task actually implements Scout, Strike, Exploit, Post-Exploit, Report, cognition loops,
capability wiring, Conductor, Policy Kernel, or agent OPSEC behavior, also read the repository's
`.devin/skills/build-blackbread-agent/SKILL.md` if present. The architecture lenses decide whether
the boundary is correct; the repository skill guides implementation behavior. Do not duplicate one
inside the other, and do not load the specialist skill for ordinary persistence, governance, or
documentation work.

## Handoff standard

The lifecycle artifacts collectively record the verified baseline, exact head when one exists,
bounded scope, non-goals, trust boundaries, RED/GREEN evidence, tests and gates, budgets, findings,
threads, gaps, claims not made, blockers, and next owner-selected slice. Each packet contains only the
fields its role can know: do not copy future CI, review, or seal sections into an implementation
packet. The final seal and session handoff assemble the relevant evidence by reference.
