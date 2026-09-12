# ADR-FINAL-006 — Access Context and Attack-Path Chaining

**Status:** ACCEPTED — 2026-09-12; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Campaign-state and execution-contract amendment

**Depends on:** `ADR-FINAL-003.md`, `ADR-FINAL-004.md`, `ADR-FINAL-005.md`

**Primary principle:** Every move starts from a known security context, produces one bounded effect,
and earns its successor context from evidence.

## 0. Decision

BlackBread SHALL chain actions through explicit security-context transitions rather than through a
tool sequence or an opaque multi-step plan:

```text
ExternalOrigin -> Primitive -> Precondition -> BoundaryTransition
-> AccessContext -> next Primitive -> ObjectiveProof
```

The `AttackPathGraph` owns candidate and verified transitions. It does not authorize execution. A
verified path is reconstructed from admitted evidence for every edge and one coherent ledger prefix.

## 1. Access context

An `AccessContext` SHALL identify what BlackBread can currently reach and as whom without exposing
raw credentials or reusable session material. Its future contract SHALL bind:

- tenant, engagement, objective, and campaign-authority reference;
- source transition and admitted evidence references;
- principal, role, tenant/account, privilege, trust boundary, and reachable origin class;
- exact host, application, cloud, network, or browser-session identity;
- opaque Session/Secret Broker handle where required;
- valid-from, expiry, revocation, cleanup, and supersession lineage;
- the coherent world snapshot from which the context was derived.

An `AccessContext` is state evidence. It is not approval, a lease, a `WorkOrder`, capability
eligibility, or permission to reuse a secret.

## 2. Atomic proposal evolution

ActionProposal v1 remains byte-stable and SHALL continue serving the active M1 path. A future
`ActionProposal` v2 SHALL add or replace references needed for chaining, including:

- `campaign_authority_ref`;
- `objective_ref`, `trajectory_ref`, and candidate `path_ref`;
- `source_access_context_ref`, with an explicit external-origin value for the first hop;
- `execution_route_ref` describing the authorized route from source context to destination;
- a coherent `world_snapshot_ref`;
- the exact target and rendered-effect description;
- `expected_security_transition`, including the boundary or privilege delta to be proved;
- oracle, evidence, cleanup, budget, idempotency, and expiry bindings.

Strategy metadata may explain the proposal but SHALL NOT change Policy admission when the exact
effect and authorization facts are otherwise identical.

## 3. Chaining loop

For each step, the owning role SHALL:

1. read a coherent campaign blackboard and current access contexts;
2. update the candidate path frontier and select one next move;
3. publish one bounded investigation intent and one atomic proposal;
4. wait for deterministic Policy, lease, and `WorkOrder` admission;
5. consume the typed outcome and admitted evidence;
6. accept, reject, or narrow the proposed state transition;
7. re-read a new coherent world snapshot before choosing subsequent work.

A failed step is information. It may block an edge, revise a hypothesis, expose a control, create a
new information gap, or cause the agent to backtrack and choose another path.

There is no fixed Scout-to-Strike-to-Exploit pipeline. A Post-Exploit observation may return to
Scout for context-aware terrain mapping, then to Strike for applicability validation, Exploit for a
new boundary proof, and Post-Exploit for objective advancement.

## 4. Batch and retry boundary

A typed adapter MAY perform deterministic bounded iteration over a declared target set, rate, depth,
deadline, and evidence contract. It SHALL NOT hide changing targets, privilege transitions, new
access contexts, or arbitrary follow-up selection inside one opaque multi-step proposal.

Every material boundary transition requires a new ActionProposal, current Policy evaluation, fresh
identity where required, a new lease or explicitly compatible current lease, and a new outcome.
Retry authority never follows merely from failure or unused budget.

## 5. Evidence and failure semantics

Each verified transition SHALL name its source context, destination context, exact effect,
capability version, oracle version, independent evidence, target identity, time validity, and cleanup
state. Screenshot evidence may support a transition but is not an independent oracle by itself.

Stale, revoked, contradictory, cross-tenant, cross-engagement, mixed-snapshot, or unproven contexts
fail closed. Replay reconstructs decisions and paths but SHALL NOT reproduce target effects.

## 6. Non-claims

This ADR does not define a production schema, implement `ActionProposal` v2, issue an access context,
or admit a capability. This ADR does not authorize target-facing execution. Those boundaries
require separate RED-first implementation slices after the active M1 trust-spine work.
