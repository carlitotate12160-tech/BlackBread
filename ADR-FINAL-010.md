# ADR-FINAL-010 — Declarative Attack Knowledge and Opportunity Frontier

**Status:** ACCEPTED — 2026-09-14; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Agent cognition, campaign planning, and knowledge-boundary amendment

**Depends on:** `ADR-FINAL-003.md` through `ADR-FINAL-009.md`

**Primary principle:** The graph describes the current board; declarative knowledge proposes legal
moves; role agents choose strategy; evidence and authorization decide what becomes real.

## 0. Decision

BlackBread SHALL replace fixed execution playbooks with a graph-driven opportunity frontier:

```text
coherent world snapshot + current access contexts + approved objective
+ versioned declarative attack knowledge + eligible capability projection
-> Opportunity Compiler
-> advisory AttackOpportunity frontier
-> owning role reasoning and specialist assessment
-> one bounded InvestigationIntent -> ready reservation -> atomic ActionProposal
-> existing Policy, lease, WorkOrder, execution, evidence, and promotion path
-> graph delta -> frontier re-evaluation
```

The system SHALL preserve five permanent reasoning roles. It SHALL NOT add a central Mission Brain,
put offensive strategy into the Conductor, or make the Policy Kernel enforce a technique order.

The implementation target combines useful architectural properties without copying another product:

| Source property | BlackBread adoption | BlackBread-specific boundary |
|---|---|---|
| graph-driven kill-chain spine | every admitted state delta can enable, invalidate, or reprioritize successor opportunities | graph state never authorizes execution |
| validated production attack maps | client output reconstructs proven paths rather than vulnerability counts | every edge retains evidence, control, authorization, and cleanup lineage |
| adaptive specialist cognition | short-lived focused reasoning can generate or challenge a candidate | specialists have no identity or execution authority |
| continuous external terrain | observations and temporal diffs reopen relevant reasoning | historical terrain is never assumed current |
| uncertainty-aware planning | beliefs and information value influence exploration | probability never becomes target truth or Policy input |
| BlackBread trust spine | every effect remains campaign-, scope-, identity-, capability-, lease-, and evidence-bound | authorization is independent from strategy quality |

This composition is a parity floor for autonomous path construction and a differentiation layer for
evidence, uncertainty, continuous terrain, authorization, and learning. Product parity remains an
empirical benchmark claim, not an architectural status.

## 1. No-playbook replacement

BlackBread rejects both extremes:

- a fixed sequence that forces Scout -> Strike -> Exploit -> Post-Exploit regardless of evidence;
- a free-form LLM that invents tools, effects, facts, or commands without typed constraints.

The replacement is three distinct artifacts:

1. **`AttackKnowledgeRegistry`** — versioned declarative knowledge about weaknesses, techniques,
   preconditions, expected transitions, evidence oracles, and capability-family bindings;
2. **`OpportunityCompiler`** — a deterministic compiler that matches that
   knowledge against one coherent current snapshot and emits typed candidates;
3. **`AttackOpportunity` frontier** — campaign-local, expiring, role-owned candidates that agents
   may rank, challenge, select, defer, or abandon.

The registry is data and constraints, not an executable script. An entry SHALL NOT encode an opaque
multi-step action, raw shell, arbitrary flags, an unbounded loop, a mandatory order, or an automatic
promotion rule. If the registry is sparse, an agent may reason from observations, request a
specialist assessment, or use the adaptive-candidate lane in `ADR-FINAL-007.md`; it may not invent an
executable capability.

## 2. Canonical state and knowledge separation

`CyberTerrainGraph` and `AttackPathGraph` remain the only campaign graph views defined by
`ADR-FINAL-003.md`. This ADR creates no third canonical graph.

| Artifact | Meaning | Authority it does not have |
|---|---|---|
| `WeaknessDefinition` | known condition, applicability predicates, base severity, and remediation | proof that a target has the condition |
| `TechniqueDefinition` | possible transition, required contexts, effect class, oracle, and capability family | executable tool or permission |
| `AttackOpportunity` | one snapshot-bound hypothesis that a transition may be worth testing | verified attack edge or reservation |
| `SpecialistAssessment` | attributed reasoning about one bounded question | agent role, target truth, or action authority |
| AttackPathGraph edge | candidate or promoted transition under existing epistemic rules | Policy, capability eligibility, or lease |

Every knowledge definition SHALL have a stable ID, immutable version, semantic digest, provenance,
validity/support state, affected product or context predicates, required observations, transition
semantics, proof and negative-control references, capability-family references, remediation, and
conflict/supersession lineage. Vendor, CVE, NVD, KEV, EPSS, community, public PoC, model, and field
sources retain separate provenance; disagreement is preserved rather than silently resolved.

Knowledge lifecycle is distinct from capability lifecycle:

```text
DRAFT -> REVIEWED -> PUBLISHED -> SUPERSEDED | RETIRED
```

Publishing knowledge cannot add a capability to `config/capability-registry.json`, promote a
candidate artifact, or make a `PLANNED`/`ON_HOLD` capability executable.

## 3. Opportunity contract

An `AttackOpportunity` SHALL bind at least:

- tenant, engagement, objective, owning role, and expiry;
- exact `WorldSnapshotRef` and source `AccessContext` or external origin;
- knowledge registry version/digest and source definition references;
- target entities and the candidate source-to-destination security transition;
- currently satisfied, missing, contradicted, and stale preconditions;
- epistemic state and uncertainty decomposition;
- required evidence oracle and negative control;
- eligible capability families as a projection reference, never copied execution permission;
- predicted information gain, objective contribution, cost, target risk, OPSEC noise, and cleanup burden;
- provenance and deduplication key.

Compiler output is advisory. Public construction, deserialization, digest recomputation, registry
substitution, stale replay, cross-tenant use, or a high score SHALL NOT satisfy a precondition,
create a verified graph edge, reserve work, or reach an executor.

Determinism describes reproducible matching, not authority. Identical versioned inputs produce the
same candidate set; role reasoning and ranking remain advisory consumers of that set. An owning
role emits an InvestigationIntent first and may emit an ActionProposal only after the deterministic
Conductor admits an active, ready reservation under ADR-FINAL-003.md.

An empty ready queue does not establish exhaustion. Pending evidence, resource waits, OPSEC holds,
and admitted in-flight work remain explicit dependencies with deadlines. Reconcile those states
before declaring frontier exhaustion; deadline or authority expiry retains its own outcome reason.

The compiler SHALL distinguish:

- `READY_TO_INVESTIGATE` — enough current evidence exists to ask the owning role to consider work;
- `NEEDS_INFORMATION` — a named observation would materially reduce uncertainty;
- `CONTRADICTED` — current evidence conflicts with the candidate;
- `BLOCKED_CAPABILITY` — no eligible capability family can produce the required proof;
- `BLOCKED_AUTHORITY` — the possible effect exceeds current campaign authority;
- `STALE` — a source fact, definition, context, or snapshot is no longer current.

These are candidate states, not Policy outcomes.

## 4. Incremental graph-driven chaining

Every admitted observation, promotion, access-context change, control assessment, capability-state
change, expiry, failure, or cleanup result SHALL trigger bounded invalidation and re-evaluation of
the affected frontier. The entire campaign need not restart, and the previous result is not mutable
LLM memory.

The re-evaluation model is:

```text
graph delta -> affected entities/contexts/definitions
-> invalidate dependent candidates
-> recompute newly possible or impossible transitions
-> owning roles independently reassess their local frontier
```

A new credential or access context may reopen an earlier destination; a failed technique may lower
only the matching context/variant; a control-blocked result may create a control assessment and an
alternative information need; a proven objective terminates further objective-directed effects.

Failures SHALL NOT globally blacklist a technique unless evidence supports that scope. A transport
failure, model refusal, stale artifact, Policy denial, target control, failed applicability oracle,
and successful negative control have different semantics and affect different dependencies.

## 5. Uncertainty-aware selection

BlackBread adopts a POMDP-style separation of hidden target state, observations, beliefs, actions,
and outcomes without requiring a general-purpose POMDP solver.

Agents MAY estimate:

- probability that a precondition holds;
- expected information gain and objective contribution;
- evidence quality and staleness;
- execution cost, target risk, OPSEC noise, and cleanup burden;
- value of preserving alternative paths.

The frontier SHALL retain this vector rather than collapse it into one globally authoritative score.
Each role applies a versioned role-specific ranking policy and records its reasoning provenance.
Deterministic code validates ranges, freshness, deduplication, budgets, and contract coherence; it
does not decide offensive utility. Model probability never becomes evidence, severity, capability
eligibility, or execution permission.

## 6. Role ownership and adaptive specialists

| Role | Owns in the frontier | Required cognitive depth |
|---|---|---|
| Scout | external or access-context terrain gaps and observation opportunities | coverage reasoning, temporal terrain diff, HVT candidates, uncertainty-driven discovery |
| Strike | applicability and precondition opportunities | proof-method competition, condition decomposition, failure disambiguation, safe variants |
| Exploit | one boundary-transition opportunity | compatibility, delivery and payload variants, successor-context prediction, cleanup plan |
| Post-Exploit | internal terrain and objective transitions | privilege/trust reasoning, internal rediscovery, bounded movement, minimum objective proof |
| Report | evidence and remediation opportunities | causal path adjudication, counterfactual remediation, minimal cut sets, retest/path diff |

An owning role may create one or more short-lived specialist assessments under the amendment in
`ADR-FINAL-003.md`. The role remains accountable for the emitted hypothesis, intent, or proposal.
Specialist count is elastic; permanent authority roles remain exactly five.

## 7. Tools, adapters, recipes, and payloads

External tools remain capability implementations. Nmap, Nuclei, native APIs, reviewed modules, and
future tools are not replaced by the knowledge registry or by LLM reasoning.

The boundary is:

```text
knowledge says what condition/transition could be tested
-> opportunity says why this target/context may justify a test
-> role selects the proof strategy
-> capability family defines the allowed effect and typed adapter
-> qualified tool/recipe/artifact performs one admitted effect
-> oracle/evidence determines the resulting graph delta
```

Parameter adaptation, `CandidateProofRecipe`, `CandidateCapabilitySource`, Capability Forge, and
`EphemeralTargetRuntime` retain the boundaries in `ADR-FINAL-007.md`. The frontier may request one of
those paths; it cannot skip qualification or use a knowledge entry as a payload.

## 8. First-principles implementation order

Implementation SHALL proceed by the smallest evidence-producing vertical consumer, not by building
a large catalog first:

1. define minimal immutable knowledge and opportunity contracts with no target consumer;
2. compile a small synthetic frontier from one coherent W2 snapshot;
3. let Passive Scout consume one opportunity in W3 and write a typed outcome;
4. add graph-delta invalidation and role-specific ranking only when a live consumer exists;
5. add Strike/Report transitions in W5 and campaign adaptation benchmarks in W6;
6. add Exploit/Post-Exploit definitions only alongside their separately qualified R3/R4 capability
   families and range proofs.

Catalog breadth follows measured coverage gaps and repeated field/range outcomes. Number of entries,
tools, or generated candidates is not a success metric.

## 9. Requirement IDs and gap

| ID | Requirement | State |
|---|---|---|
| `AKR-001` | Attack knowledge is declarative, versioned, provenance-bound, and independent of capability lifecycle. | DECIDED |
| `AKR-002` | Knowledge entries cannot encode an opaque executable playbook or directly create target truth. | DECIDED |
| `OPP-001` | Opportunity compilation is snapshot-, context-, objective-, role-, registry-, and expiry-bound. | DECIDED |
| `OPP-002` | Every relevant graph delta incrementally invalidates and re-evaluates affected candidates. | DECIDED |
| `OPP-003` | Role ranking preserves uncertainty and multi-objective tradeoffs without becoming Policy. | DECIDED |
| `OPP-004` | Five permanent roles may use advisory ephemeral specialists without delegating authority. | DECIDED |
| `OPP-005` | Tools and adaptive payloads remain qualified capability implementations, not knowledge entries. | DECIDED |

`KNOWLEDGE-GAP-001` in `GAP-REGISTER.md` owns implementation and release status.

## 10. RED-first proof obligations

- a registry entry alone creates no terrain fact, verified edge, reservation, or proposal;
- same IDs with a different registry digest or semantics fail closed;
- a mixed or stale snapshot/context produces no ready opportunity;
- cross-tenant definitions or candidates cannot enter a campaign frontier;
- a newly admitted graph delta enables a previously impossible successor without restarting the campaign;
- an invalidating delta removes or marks dependent candidates stale;
- Policy admission is invariant when only opportunity score or specialist rationale changes;
- a `PLANNED`, `ON_HOLD`, unpinned, wrong-role, or expired capability remains blocked even when ranked first;
- tool, model, control, policy, oracle, and artifact failures update only their correct dependency scope;
- no Conductor function ranks paths or selects techniques.

## 11. Non-claims

This ADR does not implement the registry, compiler, frontier, agent, graph, capability, payload,
specialist worker, or learning system. It does not populate a weakness catalog, admit a tool,
authorize target-facing execution, close an existing release gap, or claim parity with NodeZero,
Pentera, XBOW, Hadrian, or another platform.
