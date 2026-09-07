# Architecture Planning

Use this reference for new milestones, slice selection, design revisions, implementation prompts, and architecture disputes.

## Contents

1. Select the BlackBread lenses
2. Preflight decision
3. BlackBread Architecture Feasibility Gate
4. Derive the slice
5. Required slice contract
6. Finish planning

## Select the BlackBread lenses

Use the routing table in `SKILL.md` and read every applicable architecture lens completely. Record
the selected lenses and the live ADR/PRD/rule/gap/capability authorities they required. A lens is a
question set, not permission to replace repository authority with remembered prose.

## Preflight decision

Lead with exactly one decision:

- `ACCEPT`
- `ACCEPT WITH CHANGES`
- `REJECT`

Support it with live repository evidence, applicable authority, current code and schema behavior, test evidence, trust boundaries, and budget estimates. Separate proven facts from proposed design.

## BlackBread Architecture Feasibility Gate

Complete this gate before choosing files, splitting for budget, or drafting an execution prompt for
a new or materially changed boundary.

1. **Exact falsifiable claim.** State one concrete property whose violation can be demonstrated.
   Avoid words such as `securely bound`, `trusted`, `authoritative`, or `safe` without naming the
   exact fact, actor, and forbidden outcome.
2. **ADR authority.** Map the claim to live accepted decisions, requirement IDs, gaps, capability
   state, and release gates. Separate `DECIDED`, `IMPLEMENTED`, `VERIFIED`, and `RELEASED`.
3. **Component authority.** State which component may reason, promote evidence, authorize, schedule,
   issue a lease, execute, persist, or adjudicate. Reject authority obtained only through naming.
4. **Information sufficiency.** List every fact required to decide the claim and prove that the
   enforcing component possesses those facts at the decision instant. Missing facts fail the design.
5. **Producer, consumer, and reachability.** Identify who constructs each artifact, every consumer,
   whether callers can construct or deserialize it, and what durable or target-facing behavior can
   become reachable.
6. **Adversarial construction.** Attempt public construction, deserialization, recomputed digests,
   nested substitution, same-identifier/different-semantics substitution, stale replay, cross-tenant
   use, alternate producers, and direct future-consumer invocation as applicable.
7. **Boundary elimination.** Prove that the design removes the forbidden seam instead of moving it
   to a wrapper, private helper, model constructor, serializer, persistence call, or later consumer.
8. **Safe intermediate state.** Prove the slice is unreachable, fail-closed, non-executable, or
   independently safe. A prose promise that a future slice will fix a current false claim fails.
9. **Future-consumer pre-mortem.** Treat the next persistence, lease, WorkOrder, API, Gateway, or
   executor as hostile or mistaken. State what it must never infer from this artifact.
10. **Proof oracles.** Name behavioral, integration, concurrency, known-answer, and temporary
    mutation oracles that fail when the claimed property is removed. API-shape assertions alone do
    not prove a security invariant.
11. **Trust-boundary decision.** Record what the design proves and explicitly does not prove,
    especially integrity versus authenticity, policy outcome versus execution permission, graph
    reachability versus exploitability, and typed input versus verified fact.
12. **Only then budget and split.** A small slice that cannot independently preserve the invariant is
    not sealable. Never split first and hope a later wrapper will restore trust.

Return the gate in this form:

```text
APPLICABLE LENSES:
LIVE AUTHORITY:
EXACT CLAIM:
COMPONENT AUTHORITY:
INFORMATION SUFFICIENCY: PASS | FAIL
ADVERSARIAL COUNTEREXAMPLE: PASS | FAIL
PRODUCER/CONSUMER CONTINUITY: PASS | FAIL
BOUNDARY ELIMINATION: PASS | FAIL
INTERMEDIATE SAFETY: PASS | FAIL
FUTURE-CONSUMER SAFETY: PASS | FAIL
PROOF ORACLES: PASS | FAIL
TRUST-BOUNDARY CLAIMS NOT MADE:
ARCHITECTURE DECISION: ACCEPT | ACCEPT WITH CHANGES | REJECT
```

If an applicable safety field is `FAIL`, return `ARCHITECTURE NOT READY` and do not issue an
implementation prompt.

## Derive the slice

1. Restate the user-visible or engineering outcome.
2. Identify prerequisites and blocking gaps.
3. Map the dependency order and trust boundaries.
4. Find the smallest independently sealable vertical slice.
5. Prove that its intermediate state is unreachable, fail-closed, or independently safe.
6. Estimate runtime changed lines, runtime files, production-module size, migrations, and test-module size with review margin.
7. Split proactively when one change crosses independently sealable trust boundaries or is unlikely to fit honestly under repository limits.

Apply the architecture lenses before step 4. Trust boundaries determine the slice; budget only
tests whether that already coherent slice fits.

Never split into an intermediate state that exposes unsafe authority, false provenance, partial publication, or target effects. Conversely, do not keep unrelated work together merely because it shares a milestone label.

## Required slice contract

An implementation-ready plan or prompt must contain:

- verified protected-main baseline and branch;
- completed prerequisites and current gaps;
- exact scope and named production responsibilities;
- public and private boundary contracts;
- durable versus ephemeral state ownership;
- migration and rollback semantics where applicable;
- tenant, provenance, concurrency, cancellation, and failure invariants;
- explicit non-goals and intermediate reachability;
- strict RED-to-GREEN sequence and negative cases;
- real integration environment requirements;
- runtime, file, module, function, complexity, test-size, and coverage budgets;
- documentation and gap-state updates;
- seal criteria, reviewer policy from live authority, and STOP/SPLIT conditions;
- next slice without inventing a future main SHA.

## Finish planning

Do not cycle through cosmetic plan revisions. After all correctness, safety, boundary, evidence, and budget blockers are resolved, declare the plan implementation-ready. Further architecture review requires new live drift, failed proof, reproduced defect, or a stated STOP/SPLIT condition.
