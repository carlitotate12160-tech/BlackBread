# BlackBread Trust-Boundary and Provenance Lens

Use this lens for digests, result/decision models, serialization, cross-stage handoffs, persistence,
ledger events, provenance, tenant isolation, RLS, producer identity, registry/manifest authenticity,
or replay. This lens exists to prevent a typed or digest-bound object from being mistaken for proof
of who produced it or what it may authorize.

## Contents

1. Evidence classes
2. Artifact trust map
3. Construction and substitution attacks
4. Durable provenance and replay
5. Required proof and rejected claims

## Evidence classes

Classify each input and output before designing its API:

| Class | Meaning | Permitted claim |
| --- | --- | --- |
| Caller-supplied typed fact | Structurally valid value supplied across the public boundary | Schema/coherence only |
| Internally computed ephemeral value | Produced inside the current composed call | Current-call computation continuity, if no injectable seam exists |
| Durable authoritative record | Written through the accepted transactional authority | Durable provenance only to the extent enforced by constraints, lineage, and access control |
| Authenticated external fact | Verified signature/MAC/attestation/registry source under accepted key authority | Producer identity and bounded signed semantics |
| Projection/read model | Deterministically derived from a verified ledger prefix | Rebuildable derived state, never independent canonical truth |

State separately whether an artifact has integrity, authenticity, freshness, authorization meaning,
and execution authority. One property never implies another.

## Artifact trust map

Every cross-stage artifact requires this completed table:

| Artifact | Producer | Consumers | Caller constructible/deserializable | Integrity source | Authenticity source | Freshness owner | Execution authority |
| --- | --- | --- | --- | --- | --- | --- | --- |

Reject vague producers such as `the system`, `internal code`, `private builder`, or `validated model`.
Name the actual function/service/transaction and every production consumer. Inspect future consumers,
not only the current unwired slice.

Use these equations as hard reminders:

```text
hash(payload) = content consistency / tamper evidence
hash(payload) != producer authentication
strict schema != verified fact
frozen model != construction authority
private Python name != security boundary
valid deserialization != trusted provenance
same IDs != same semantic object
policy outcome != execution permission
ledger presence != verified target fact
```

## Construction and substitution attacks

Before accepting a wrapper, binding, result, decision, snapshot, or token-like object, attempt:

- ordinary constructor and public factory;
- `model_validate`, `model_validate_json`, and equivalent deserialization;
- bypass construction such as `model_construct` where the framework exposes it;
- payload modification followed by digest recomputation;
- nested object replacement while preserving outer identifiers;
- same tenant/engagement/proposal/capability IDs with different security-relevant semantics;
- strong upstream result paired with weaker downstream facts;
- stale but structurally valid replay;
- cross-tenant and cross-engagement substitution;
- alternate producer creating the same shape;
- direct invocation of the next persistence, lease, WorkOrder, Gateway, API, or executor consumer.

If anyone who can replace the payload can also create the proof, the proof is not producer
authentication. Removing a convenience constructor does not remove construction authority.

Prefer eliminating an injectable seam through composition: accept an authoritative input once,
compute intermediate results inside the owner, and keep the same value through dependent semantics.
Do not replace a seam with a serializable wrapper unless an accepted authenticity authority actually
exists and is verified by the consumer.

## Durable provenance and replay

For persistence, define the transaction that joins evaluation, durable decision lineage, ledger
publication, idempotency, and any outbox. A repository must not accept a caller-supplied serialized
`PolicyDecision`, `AdmissionResult`, `RuntimeGateResult`, binding, or lease as authoritative merely
because its fields and digest validate. Compose evaluation with persistence behind the controlled
boundary or verify a separately accepted producer credential.

Bind durable records to tenant, engagement, proposal digest, graph/world snapshot or ledger prefix,
policy/runtime facts, capability version and supply-chain identity, target identity, decision time,
outcome/reason, and predecessor/supersession data required by the live contract. Use database
constraints and RLS as enforcement, not filtering as proof. Test with the bypass-capable role and
verify that invalid rows cannot exist, not merely that a tenant query hides them.

Replay begins only from a verified chain and committed snapshot. Recompute deterministic projections
from the exact prefix and explicit `as_of`; reject mixed anchors, unsupported versions, forks,
sequence regressions, stale heads, and cross-tenant references. Replay of recorded external outcomes
must not re-run target effects.

Manifest, capability-registry, platform-key, and external attestation authenticity must name the key
authority, algorithm/version, rotation/revocation behavior, signed preimage, freshness, and failure
mode. If the current slice merely receives typed snapshots, state that limitation and do not claim
registry or manifest producer authenticity.

## Required proof and rejected claims

For each semantic digest field, use a stale-digest mutation with a valid alternate value. Separate
schema/coherence failures from digest failures. Use an independently calculated known-answer vector
for sealed preimages. When an oracle's sensitivity is uncertain, temporarily remove one protected
field, confirm the security test fails because tampering is accepted, restore it, and rerun GREEN.

For producer continuity, use a behavioral regression—not only source inspection or absence of a
method name. Prove that the public signature has no injectable intermediate and that the real
upstream computation runs over the same authoritative input. For intentional non-wiring, prove there
is no production consumer and state what the next consumer must not infer.

Reject claims such as `unforgeable`, `trusted`, `authentic`, `only constructible internally`,
`producer-bound`, `current`, or `execution-authorizing` unless the enforcing mechanism and consumer
verification are implemented and tested in the current slice. A later milestone may own stronger
provenance only when the current intermediate is independently safe and makes no false claim.
