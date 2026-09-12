# ADR-FINAL-005 — External-to-Objective Product and Campaign Authority Envelope

**Status:** ACCEPTED — 2026-09-12; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Product, autonomy, and authorization-boundary amendment

**Amends:** `ADR-FINAL-002.md` §§1–4, 7–8, 11–14, 20–26, 31, 35–36, 40;
`ADR-FINAL-003.md` §§10–16; `ADR-FINAL-004.md` §§0–5; `PRD.md`

**Primary principle:** The agent chooses the next move; deterministic controls decide whether its
exact effect is currently permitted.

## 0. Decision

BlackBread's product north star SHALL be a **Verified External-to-Objective Attack Path**:

```text
authorized external origin -> discovered entry -> verified boundary transitions
-> internal access contexts -> approved business objective -> control assessment -> cleanup
```

Recon-only remains a useful entry product and release gate. It SHALL NOT redefine BlackBread as a
scanner or make one isolated finding the final architecture target.

The client promise is:

> BlackBread begins outside the perimeter, autonomously finds and proves a complete authorized path
> to an agreed business objective, records every boundary crossed, and measures where controls
> detected, delayed, blocked, or failed to stop it.

`Complete` means the full proven chain from its declared external origin to the approved objective.
It does not mean that every asset or every possible path in the client's network was assessed.
Campaigns run without advance blue-team notice when the signed engagement permits that posture;
BlackBread cannot guarantee non-detection. Detection is a reportable defensive outcome.

This direction is evidence-led. Anthropic reports that agentic systems can loop, chain tasks, and
operate with only occasional human input; its cyber-range work also demonstrates multistage attacks
using standard open-source tools. The same reporting records hallucinated credentials and false
claims, so BlackBread couples autonomy to evidence promotion rather than trusting model narration.

## 1. Campaign authority

A full-kill-chain engagement SHALL carry a durable, signed `CampaignAuthorityEnvelope`. It is an
**authority ceiling**, not execution permission and not a reusable bearer token.

The envelope SHALL bind at least:

- tenant, engagement, sponsor attestation, validity window, and revocation lineage;
- external starting origin and approved business objective or objective set;
- exact scope, exclusions, third-party boundaries, and permitted execution routes;
- maximum effect tiers and capability families by target class;
- allowed access-context, privilege-transition, and lateral-movement classes;
- request, action, path, cost, concurrency, target-health, and OPSEC budgets;
- evidence, cleanup, reconciliation, retention, and disclosure obligations;
- effects that always require a new operator escalation.

The signed envelope authorizes a bounded campaign class. It SHALL NOT itself issue a lease, create a
`WorkOrder`, activate a registry capability, prove a graph edge, or promote evidence.

## 2. Autonomous move contract

Inside a current envelope, agents MAY select hypotheses, paths, techniques, capabilities,
parameters, alternatives, retries, deferrals, and abandonment without per-hop human approval.

Policy evaluates every exact effect against the current envelope, scope, target identity,
capability lifecycle, rendered destinations, approval class, budgets, locks, OPSEC/health state,
cleanup obligation, and current world snapshot. A passing decision still requires a current lease
and exact `WorkOrder` before any target effect becomes reachable.

A new operator decision is required only when the proposed effect would exceed the envelope, change
the objective or scope, enter an excluded target class, use a capability requiring exact escalation,
or recover target-active work after `BURNED`.

For full-kill-chain campaigns, this supersedes earlier references to a separate human approval for
every Exploit/Post-Exploit hop. The signed campaign envelope satisfies human authorization for the
effect classes it expressly includes; every exact effect still needs a fresh deterministic Policy
decision, lease, and `WorkOrder`. It does not become blanket auto-approval.

The Policy Kernel SHALL NOT require a fixed stage order, preferred technique, playbook completion,
path score, model confidence, or human approval merely because another autonomous hop occurred.

## 3. Five-agent campaign behavior

BlackBread remains a five-agent decentralized-cognition system with no Mission Brain. The system is
the chess player; the agents are bounded reasoning roles over one objective and one coherent world
snapshot.

- Scout maps terrain from the current external or access context.
- Strike verifies a candidate primitive or precondition without crossing a boundary.
- Exploit proves an approved boundary transition and produces evidence for a new access context.
- Post-Exploit reasons over internal terrain and advances the approved objective through dedicated
  post-access capabilities.
- Report independently adjudicates edges, impact, coverage, detection, and cleanup.

Role transitions are typed requests, not commands. Roles MAY loop, revisit, or switch paths; there is
no mandatory Scout-to-Strike-to-Exploit-to-Post-Exploit pipeline.

## 4. Evidence and terminal states

An objective is satisfied only by promoted evidence under its declared impact oracle. Candidate
terrain, a vulnerability match, a successful tool exit, a screenshot, model agreement, or graph
reachability alone cannot satisfy it.

A campaign terminates as `OBJECTIVE_PROVEN`, `CONTROL_BLOCKED`, `DETECTED_AND_STOPPED`,
`FRONTIER_EXHAUSTED`, `AUTHORITY_EXHAUSTED`, `BUDGET_EXHAUSTED`, `OPERATOR_STOPPED`, or
`INCONCLUSIVE`. Reports SHALL separate verified paths from candidate, blocked, exhausted, and
unassessed paths.

Non-normative primary sources:

- [Anthropic: AI-orchestrated cyber espionage campaign](https://www.anthropic.com/news/disrupting-AI-espionage)
- [Anthropic: realistic cyber-range and open-source-tool results](https://www.anthropic.com/research/cyber-toolkits-update)

## 5. Compatibility and release placement

`ActionProposal` v1 remains unchanged for the active M1 trust-spine work. A future versioned
contract may bind the campaign envelope; it SHALL NOT reinterpret or mutate the v1 digest preimage.

This ADR does not authorize target-facing execution, close `LEDGER-GAP-001` or
`CAMPAIGN-GAP-001`, admit any capability, or release full-kill-chain mode. Implementation requires
the follow-on contracts in `ADR-FINAL-006.md` through `ADR-FINAL-009.md` and their release evidence.
