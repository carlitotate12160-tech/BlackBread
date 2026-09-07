# BlackBread Control-Plane Architecture Lens

Use this lens for Policy Kernel, Conductor, OPSEC, approvals, budgets, locks, execution leases,
scheduling, cancellation, halt, cleanup coordination, resume, or replay. Read the live accepted ADR,
PRD, rules, gap register, current policy/conductor implementation, and relevant persistence authority.

## Contents

1. Control-plane chain
2. Component authority
3. State and authorization invariants
4. Concurrency, time, halt, and replay
5. Proof obligations and stop conditions

## Control-plane chain

Preserve this staged authority path:

```text
ActionProposal -> Policy evaluation -> durable decision record
-> execution lease -> WorkOrder -> Capability Gateway -> exact invocation
-> typed outcome/evidence -> canonical ledger -> deterministic projections
```

Each arrow is a trust boundary. Identify its producer, consumer, state owner, freshness rule,
idempotency key, failure behavior, and whether a caller can inject an intermediate artifact. Compose
stages when accepting two independently supplied facts would permit substitution.

No intermediate policy result, reservation, approval, graph path, scheduler choice, runtime-gate
pass, or serialized decision authorizes execution. Target effect becomes eligible only through the
current lease and WorkOrder path defined by the live milestone contract.

## Component authority

| Component | Owns | Forbidden authority |
| --- | --- | --- |
| Policy Kernel | Deterministic decision over the exact proposal/rendered semantics and current verified facts | Offensive strategy, tool improvisation, persistence, scheduling, or execution |
| Conductor | Readiness, dependencies, fair non-strategic scheduling, reservations, budgets, locks, leases, cancellation, and cleanup coordination | Hypothesis creation, technique selection, offensive path value, impact inference, or evidence promotion |
| OPSEC service | Deterministic heat, pacing limits, target-health signals, hard stop, and recovery eligibility | Strategy, scope expansion, or LLM-overridable danger decisions |
| Lease authority | Time-bounded, objective/capability/target-bound execution permission | Broad engagement permission, reusable token, or policy replacement |
| Executor | One exact bounded invocation from an admitted WorkOrder | Follow-up selection, parameter expansion, scope changes, retries without a new decision, or truth promotion |
| Ledger/projections | Canonical event history and deterministic views | Treating every event as verified target truth or inventing missing decisions |

Keep strategy decentralized in agents while centralizing deterministic safety. Never hide strategic
ranking in a readiness score, scheduling priority, retry policy, budget rule, or OPSEC calculation.

## State and authorization invariants

For every component, declare durable state, ephemeral state, caller-supplied facts, transaction owner,
and mutation authority. Require tenant and engagement binding throughout. Bind proposal, exact target,
rendered destinations, capability version/supply chain, identity tier, approvals, budgets, locks,
policy/runtime facts, decision, lease, WorkOrder, and cleanup obligation as required by the stage.

Maintain these negative invariants:

- `ALLOW` is a policy outcome, not execution permission.
- Approval is not a lease; a reservation is not a lock; a lock is not a lease.
- A verified graph path cannot activate a capability or bypass policy.
- A lease cannot broaden the decision, target, capability, parameters, network path, budget, or expiry.
- A WorkOrder cannot exist without a current valid lease and exact decision lineage.
- Revoked, expired, stale, missing, contradictory, cross-tenant, or cross-engagement facts fail closed.
- No component may infer authenticity from a digest or a model's `decision_authority` field.
- No final decision may bypass the exact rendered-destination validation owned by the execution path.

Keep outcome and reason vocabularies closed and coherent. Define fixed precedence where several gates
fail. Do not preserve unreachable reasons or invent semantics merely for backwards-looking symmetry.

## Concurrency, time, halt, and replay

Use caller-supplied explicit UTC evaluation times for pure functions. At mutable boundaries, identify
the serialization point and enforce optimistic revision, row lock, unique constraint, transactional
outbox, or another deterministic mechanism appropriate to the live design.

Budgets and locks must be checked and reserved atomically. Lease issuance must not race revocation,
engagement stop, budget exhaustion, lock acquisition, target-identity expiry, or OPSEC transition.
Tests must force the relevant interleavings with barriers/events or database transactions; sleeps and
repetition are not proof.

Preserve the stop semantics:

- `BURNED` freezes target-active work and requires operator-authorized recovery, fresh identity, and
  a new lease.
- Engagement stop, kill switch, dead-man halt, cancellation, and lease revocation prevent new work and
  deterministically reconcile in-flight state according to the accepted mode.
- Resume revalidates mutable authority and target identity; elapsed time does not make stale facts true.
- Low-and-slow sleep is deferred scheduling, not a sleeping worker holding hidden authority.

Replay must reconstruct the same decisions and projections from the verified ledger prefix without
duplicating budget reservation, lock ownership, lease, WorkOrder, target effect, or cleanup. External
effects require idempotency and reconciliation; deterministic replay must not re-execute them.

## Proof obligations and stop conditions

Require behavioral proof for fail precedence and authority separation; real PostgreSQL for RLS,
transactions, locks, durable idempotency, replay, or persistence; deterministic cancellation and
concurrency tests; and boundary tests proving no unauthorized importer or alternate execution path.

Before acceptance, answer:

```text
Can a caller supply a decision/runtime/admission artifact separately from the facts that produced it?
Can any path issue a WorkOrder without the current lease?
Can scheduler, graph, model confidence, or OPSEC state select offensive strategy?
What mutable facts can change between decision and execution, and where are they revalidated?
What happens on cancellation after each durable write or external effect?
Can replay duplicate authority or target effects?
Can cross-tenant identifiers meet through lookup, join, cache, or serialized input?
```

Stop or split when policy semantics, durable mutation, lease issuance, and execution wiring cannot be
proven as one safe boundary within budget. Never publish a partially authoritative intermediate or
defer a bypass created by the current public API to a later slice.
