# ADR-FINAL-004 — Vertical Delivery, Policy Minimalism, and Agent Autonomy

**Status:** ACCEPTED — 2026-09-11; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Delivery-order and authority-boundary amendment

**Amends:** `ADR-FINAL-002.md` §§0, 7, 21, 28, 35, and 36; `ADR-FINAL-003.md` §§2, 13, 16, and 18

**Amended by:** `ADR-FINAL-005.md` — External-to-Objective Product and Campaign Authority Envelope
(accepted 2026-09-12)

**Retains:** every law, SOW, signed-manifest, scope, target-identity, capability-lifecycle, OPSEC,
do-no-harm, tenant-isolation, evidence-integrity, cleanup, and release gate in the amended ADRs

**Primary principle:** Policy constrains exact effects; agents choose strategy; vertical evidence proves progress

## 0. Decision

BlackBread SHALL be delivered as a sequence of executable vertical loops, not as isolated deep
subsystems. The immediate objective is an adaptive external-red-team control loop whose behavior is
replayable and whose effects remain bounded:

```text
signed objective + verified world state
  -> agent hypothesis and investigation intent
  -> ActionProposal
  -> Policy decision
  -> Conductor work order + lease
  -> bounded capability execution
  -> outcome + evidence
  -> canonical Event Ledger
  -> coherent world and campaign projections
  -> next agent observation
```

The minimum executable proof for a delivery wave is:

```text
proposal -> decision -> work order -> outcome -> ledger
```

At first this proof MAY use a deterministic simulated capability and synthetic target. A wave does
not become target-facing merely because the control loop exists. Real-target execution remains
blocked until its existing release gates are verified.

BlackBread adopts the useful operational qualities associated with the earlier Decepticon
brainstorming and autonomous-pentest systems: persistent objective pursuit, local planning,
evidence-grounded reprioritization, bounded execution, independent verification, and recovery when a
path stalls. These are acceptance qualities, not a product-copying decision and not permission to
introduce a central strategist.

## 1. Failure mode being corrected

The repository has a strong ledger and a comparatively mature deny-side Policy Kernel, while the
Conductor execution path, agents, Capability Gateway, executor, and multi-view world model remain
incomplete. Continuing to deepen only Policy would produce a formally guarded system that cannot
perform useful authorized work. That repeats the Agent-Alpha failure mode: safety expressed as a
static playbook makes the agent rigid, prevents alternate-path reasoning, and can reduce useful
execution to zero.

The correction is not to remove safety. The correction is to keep deterministic control narrow and
effect-based while moving delivery effort across every boundary needed by one working loop.

## 2. Authority allocation

| Component | Owns | Must not own |
|---|---|---|
| Role agent | hypotheses, information gaps, path selection, technique selection, capability choice, parameters, retry/defer/abandon decisions | execution authority, claim promotion, mutable canonical truth |
| Event Ledger | ordered canonical facts and provenance | inferred world truth or strategy |
| Verified World Model | deterministic, coherent projections from one verified ledger prefix | action authorization or mutable LLM memory |
| Policy Kernel | whether one exact rendered effect may occur now | offensive strategy, tool order, required playbook stage, path ranking |
| Conductor | readiness, dependency checks, leases, locks, budgets, fairness, cancellation | offensive planning or strategic path ranking |
| Capability Gateway and executor | typed adapter lifecycle, rendering, isolation, destination enforcement, evidence capture, cleanup | bypassing Policy/Conductor or promoting findings |
| Report | independent evidence adjudication and coverage honesty | execution authority or rewriting source evidence |

The Verified World Model remains one coherent bundle derived from the canonical ledger:

```text
Event Ledger
  -> WorldSnapshotRef
     -> CyberTerrainGraph
     -> AttackPathGraph
     -> ControlAssessmentProjection
     -> CampaignProjection
```

No projection is a second canonical database. All four views SHALL bind to the same verified ledger
anchor and `as_of` instant before an agent may reason over them together.

## 3. Policy minimalism contract

**Policy outcome is invariant under strategy metadata.** For two proposals with the same exact
rendered effect and the same authorization facts, changing only the agent's hypothesis, path,
technique, tool order, playbook label, or reasoning trace SHALL NOT change admission.

The Policy Kernel MAY evaluate only facts required to decide whether the exact effect is permitted:

- signed engagement and objective authority;
- tenant and exact scope binding;
- target identity required by the effect and network path;
- admitted capability identity, version, owner, and lifecycle;
- rendered destinations and prohibited effects;
- approval, budget, lock, lease, time window, and concurrency state;
- OPSEC and do-no-harm state;
- cleanup and evidence obligations appropriate to the effect.

Policy SHALL NOT require a static Scout-to-Strike-to-Exploit sequence, a mandatory tool order, a
specific hypothesis, a preferred technique, a minimum LLM confidence, or completion of a playbook
stage. Cross-role prerequisites exist only when a concrete effect or evidence oracle requires them.

Every new `DENY` rule requires all of the following in the same slice:

1. a concrete forbidden effect;
2. its law, SOW, signed-manifest, scope, safety, or lifecycle authority;
3. an adversarial counterexample showing the bypass if the rule is absent;
4. an adjacent positive control proving that authorized neighboring behavior remains possible;
5. a machine-readable reason and recovery path.

“Best practice,” strategic preference, or playbook order is insufficient authority for a Policy
denial. A proposal may still be invalid because it lacks information; that condition belongs in
readiness or agent feedback unless executing the exact effect would itself be unauthorized or unsafe.

### Progressive effect tiers

| Tier | Minimum deterministic guardrails | Strategy left to the agent |
|---|---|---|
| T0 passive/offline | manifest, tenant/data provenance, source terms, cost and retention; target identity may be absent when network path is `NONE` | sources, ordering, correlation, hypothesis generation |
| T1 active read-only | T0 plus exact scope/identity, destination rendering, lease, request budget, pacing and OPSEC | endpoints, observation sequence, alternative paths |
| T2 sensitive validation | T1 plus exact approval, risk oracle, lockout/health margin and bounded retry | safest valid validation approach |
| T3 boundary/impact proof | T2 plus fresh identity, approved objective, range-qualified capability, cleanup and reconciliation | which approved proof best resolves the objective |

The tier system is a progressive effect envelope, not a maturity ladder that forces every agent
through a fixed sequence.

## 4. Balanced delivery constraints

The following rules govern slice selection after this ADR merges:

1. No subsystem receives more than two consecutive release-bearing slices unless a reproduced P0/P1
   safety blocker requires it and the owner records the exception.
2. A new schema or event requires a named consumer in the same slice or the immediately following
   selected slice. A speculative schema without a named consumer is rejected.
3. Every wave ends with one replayable executable scenario and explicit negative controls.
4. After the already-selected `M1.4c2b0b` and its bounded `M1.4c2b1` companion, no new Policy-only
   feature may be selected until the R0 closed loop and the Passive Scout loop exist.
5. Producer and consumer maturity may differ by at most one wave on a release path.
6. Progress is measured by connected trust-boundary edges and proved outcomes, not lines of code,
   number of rules, number of schemas, or test count alone.
7. The capability registry defines affordances and effect envelopes. It must not become a playbook.

These constraints do not prevent focused corrections. They prevent an entire roadmap from advancing
one authority while its producers or consumers remain absent.

## 5. Revised implementation roadmap

The existing M0-M6 milestones and R0-R5 release gates remain product gates. The waves below change
delivery order inside those gates so BlackBread reaches useful closed loops earlier.

| Wave | Deliverable | Executable exit proof | Existing gate/gap relationship |
|---|---|---|---|
| W0 — reset and verify | Merge this authority correction; reconcile local, protected-main, and private Oracle runtime evidence without uploading secrets or host state | clean baseline, green governance, explicit next slice and no false runtime claim | governance only; does not release M1 work |
| W1 — R0 closed loop | Finish only the minimum `M1.4c2b0b`/`M1.4c2b1` decision envelope; add the Conductor decision consumer, budgets/locks/lease, work order, halt/kill path, and deterministic simulated executor | an authorized synthetic proposal completes `proposal -> decision -> work order -> outcome -> ledger`; denied, expired, duplicate, and halted cases cannot execute | closes `LEDGER-GAP-001` only when its full verification evidence exists; R0 remains blocked until then |
| W2 — Verified World Model v1 | Add truth-class events, one `WorldSnapshotRef`, and minimal coherent `CyberTerrainGraph`, `AttackPathGraph`, `ControlAssessmentProjection`, and `CampaignProjection` | one synthetic ledger replay rebuilds all views at the same anchor; terrain reachability creates no attack edge and control state does not erase the underlying condition | begins `CAMPAIGN-GAP-001`; no target capability yet |
| W3 — Passive Scout | Add minimum Capability Gateway lifecycle, artifact contract, passive asset capability, fresh context envelope, and Scout local OODA | Scout forms a hypothesis, proposes passive work, receives evidence, updates the world model, and chooses continue/defer/abandon without a static playbook | first agent loop; capability admission tests required; no direct target contact |
| W4 — T1 recon | Add scope-locked DNS/TLS/HTTP observation, controlled egress, OPSEC pacing, redirect/destination validation, and control-effect observation | Scout adapts after blocked, stale, duplicate, and source-outage outcomes while remaining inside T1 budgets | first target-active candidate; still ineligible until all R1 entry gates pass |
| W5 — restricted Strike + Report | Promote supported attack-path candidates, run restricted Strike verification, adjudicate independent evidence in Report, and produce a ProofArtifact | synthetic-to-range Scout -> restricted Strike -> Report finding with honest inconclusive/control-blocked branches | closes the R1 portions of `CAMPAIGN-GAP-001` only with the conformance record |
| W6 — campaign adaptation | Add bounded trajectories, reservations, deduplication, information-gap feedback, stall/exhausted handling, and campaign benchmarks | path-value reversal, local disagreement, restart/replay, and no-brain benchmarks pass without Conductor strategy | completes campaign-coherence obligations needed by R1 |
| W7 — higher-risk modes | Add R2 authenticated reconnaissance, then separately range-qualify T2/T3 Strike, Exploit, and Post-Exploit capabilities | each effect tier passes its own approval, abort, cleanup, reconciliation, and negative-control suite | R2/R3/R4 remain independent hard release gates |

`M1.4c2b0b` remains the selected next release-bearing slice. Its scope SHALL remain bounded to the
missing decision-envelope behavior already selected on protected main; it is not permission to add
new strategic rules. If private Oracle verification reproduces a credential/bootstrap defect that
prevents the slice's tests or runtime proof, that defect SHALL be isolated as a prerequisite slice and
no sensitive Oracle material may enter Git.

## 6. Decepticon-derived decisions and timing

The earlier brainstorming is scheduled as architecture work, not discarded:

| Decision | Delivery point | Boundary condition |
|---|---|---|
| halt/resume/reconciliation contract | W1, before R0 exit | deterministic control-plane state; no agent strategy |
| minimal artifact identity and provenance | W3, before the first capability | references and lifecycle only; full report materialization waits for W5 |
| Capability Gateway lifecycle and rendering boundary | W3, before the first capability | every invocation remains typed, isolated, destination-checked, and evidence-producing |
| fresh context envelope | W3, before Scout OODA | coherent snapshot and authority facts; no hidden mutable memory |
| advisory middleware | after the W3 boundary exists, as a separate slice if it has a distinct authority boundary | advisory output cannot authorize, promote truth, or execute |
| campaign blackboard and deterministic reservations | minimal projection in W2, active coordination in W6 | no Mission Brain and no Conductor path ranking |
| no-brain and path-reversal benchmarks | W6 | benchmark failure may justify a future ADR, not silent central cognition |
| ADR index, generated quality bar, and PR risk tiers | one governance-only slice after R0 | must not displace W1-W3 runtime work |

No Decepticon item authorizes a static action playbook. A playbook MAY be an advisory tactic library
or test fixture, but the agent remains free to choose, reorder, skip, or abandon tactics inside the
current effect envelope.

## 7. Proof obligations

| Invariant | Required proof |
|---|---|
| strategy-invariant Policy | property/parameterized tests vary hypothesis, path, technique, tool order, and playbook metadata while exact effect facts remain equal; admission is unchanged |
| adjacent positive control | every new deny case includes a permitted neighbor and a typed recovery outcome |
| no direct execution | a proposal cannot reach an executor without allowed Policy decision, work order, and current lease |
| vertical liveness | every wave's exit scenario reaches its named consumer and writes the expected ledger outcome |
| coherent world model | all views share one verified ledger anchor and `as_of`; mixed anchors fail closed |
| adaptive local cognition | changed admissible evidence changes agent intent; unchanged evidence cannot consume unbounded work |
| no central brain | Conductor tests contain no offensive path ranking; agents may disagree without truth by vote |
| honest release status | conformance records distinguish decided, implemented, verified, and released behavior |

## 8. Explicit non-claims

This ADR does not implement an agent, does not admit a capability, does not authorize target-facing execution,
and does not claim parity with NodeZero or any other product. It defines the delivery order and
falsifiable boundaries required to build those operational qualities without weakening BlackBread's
authorization and do-no-harm trust spine.

It also does not close `LEDGER-GAP-001`, `CAMPAIGN-GAP-001`, any capability admission blocker, or any
release gate. Those states change only through their specified automated evidence and conformance
records.
