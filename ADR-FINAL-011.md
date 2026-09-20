# ADR-FINAL-011 — Evidence-Qualified Learning and Memory Planes

**Status:** ACCEPTED — 2026-09-14; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Learning, memory, provenance, and continuous-improvement amendment

**Depends on:** `ADR-FINAL-003.md`, `ADR-FINAL-004.md`, `ADR-FINAL-006.md`,
`ADR-FINAL-007.md`, `ADR-FINAL-009.md`, and `ADR-FINAL-010.md`

**Primary principle:** A task may end, but evidence-qualified experience compounds; history informs
the next decision without being mistaken for current target truth.

## 0. Decision

BlackBread SHALL be system-stateful even when an individual LLM invocation is stateless. Completed,
failed, blocked, refused, expired, and inconclusive work SHALL produce typed outcomes that can improve
future reasoning after evidence qualification.

The learning loop is:

```text
typed action/outcome + evidence/control/cleanup lineage
-> deterministic outcome classification
-> campaign-local state update
-> evidence-qualified experience candidate
-> tenant/global promotion boundary
-> versioned priors, ranking features, knowledge candidates, and range scenarios
```

Historical state is a prior, never current truth. No memory record may directly satisfy a target
precondition, create a verified graph edge, activate a capability, authorize an action, or support a
client claim about the present engagement.

## 1. Four memory planes

| Plane | Lifetime and scope | Permitted use | Forbidden inference |
|---|---|---|---|
| Task scratch | one cognition attempt; ephemeral | intermediate reasoning, candidate comparison, tool-output parsing | durable truth or resume authority |
| Campaign memory | one tenant/engagement; ledger-backed | current hypotheses, outcomes, trajectories, access contexts, frontier, and replay | cross-engagement reuse or hidden mutable LLM memory |
| Tenant longitudinal memory | one tenant across authorized engagements; retention-bound | temporal terrain diff, recurring patterns, remediation/retest history, contextual priors | current exposure without re-observation |
| Global experience | de-identified/aggregated or explicit opt-in; versioned | general technique priors, failure patterns, benchmark/range candidates, knowledge proposals | tenant facts, secrets, target identity, or executable promotion |

Campaign memory uses the canonical ledger and deterministic projections already defined by
`ADR-FINAL-003.md`; it is not a second store of truth. Tenant and global planes SHALL declare their
provenance, retention, consent/legal basis, privacy transformation, version, and allowed consumers.
Raw secrets, customer content, reusable credentials, private exploit artifacts, screenshots, and
identifying evidence SHALL NOT enter global experience.

## 2. Technique outcome contract

Every attempted or intentionally unattempted opportunity SHALL produce a typed `TechniqueOutcome`
with an explicit attempted-effect discriminator. Selection, deferral, rejection, and expiry before
dispatch are decision outcomes, not execution attempts; exclude them from execution-success
denominators. Proposal, lease, WorkOrder, artifact, and target-evidence references are absent when
their corresponding stages were never reached, rather than fabricated. Bind applicable outcomes to:

- tenant, engagement, objective, role, trajectory, opportunity, and proposal references;
- exact world snapshot, source access context, knowledge/technique version, capability family and
  artifact identity when applicable;
- Policy decision, lease, WorkOrder, execution route, target identity, and timestamps when an effect
  was admitted;
- declared expected transition and oracle;
- observation, evidence, control-assessment, promotion, cleanup, and successor-context references;
- normalized outcome class and reason code;
- information gained, uncertainty delta, objective contribution, cost, OPSEC/health signals, and
  whether the result is eligible for experience promotion.

Outcome classes SHALL include:

- `PROVED` — the declared oracle admitted the expected claim or transition;
- `DISPROVED` — a valid negative control or oracle disproved the exact candidate;
- `CONTROL_BLOCKED` — a tested defensive control prevented the effect while the underlying condition
  remains separately represented;
- `POLICY_DENIED` — current authorization/safety facts rejected execution;
- `AUTHORITY_EXPIRED` — campaign, context, artifact, decision, lease, or task validity elapsed;
- `TOOL_OR_ADAPTER_ERROR` — execution machinery failed before a target conclusion was available;
- `TARGET_UNSTABLE_STOP` — health or safety stop ended the attempt;
- `MODEL_REFUSAL` — a model declined the bounded cognition task;
- `CANCELLED` or `OPERATOR_STOPPED`;
- `INCONCLUSIVE` — evidence cannot support either the positive or negative claim.

A Policy denial is not exploit failure. A tool error is not a safe target. A model refusal is not a
technical impossibility. A blocked control is not absence of the underlying condition. Cleanup
failure is recorded independently and can block further effects even when the proof succeeded.

## 3. Evidence-qualified promotion

Experience promotion SHALL be a deterministic, attributable process. A successful model narration,
tool exit code, screenshot, repeated vote, or ledger presence is insufficient.

An experience candidate MAY be promoted only when it has:

- canonical input and outcome semantics;
- exact knowledge, prompt/model, capability, adapter, artifact, oracle, and environment versions;
- target-context features appropriate to the intended reuse scope;
- admitted evidence or a reason class that does not require target evidence;
- contradiction and duplicate handling;
- tenant consent/isolation and retention checks;
- a named producer, promotion authority, validity window, and supersession lineage.

Promotion targets are distinct:

1. **campaign update** — immediate deterministic projection from the current engagement ledger;
2. **tenant prior** — contextual history retained only for that tenant and revalidated next time;
3. **global aggregate** — privacy-reviewed statistics with minimum aggregation/de-identification;
4. **knowledge candidate** — a proposed weakness/technique definition requiring the independent
   review and publication lifecycle in `ADR-FINAL-010.md`;
5. **range scenario** — a reproducible fixture generated by the Experience-to-Range Compiler.

No promotion target can mutate the capability registry or sign an executable artifact.

## 4. Contextual ranking and temporal decay

Learning SHALL adjust advisory priors and ranking features by context, not create a universal success
score. Context may include product/version family, protocol, control pattern, access context,
platform/architecture, capability/artifact version, evidence quality, recency, and engagement mode.

Each prior SHALL retain sample size, outcome distribution, uncertainty interval, source population,
last observation, decay function, applicable context, and known bias. Contradictory outcomes remain
visible. Sparse evidence widens uncertainty instead of producing false precision.

Temporal decay SHALL reduce reliance on old observations and outcomes. It SHALL NOT delete historical
provenance or silently convert old success into present applicability. A new engagement begins with
an empty set of current target facts even when tenant history supplies useful hypotheses.

Agent ranking consumes a versioned `LearningSnapshotRef` beside, not inside, the coherent
`WorldSnapshotRef`. This prevents historical priors from contaminating the target-state root.

## 5. No online self-modifying model

BlackBread SHALL NOT fine-tune or rewrite a production model, prompt, policy, registry, oracle, or
ranking function autonomously from live campaign outcomes.

Model, prompt, feature, prior, registry, and ranking changes are immutable versions with offline
evaluation, reproducible benchmark evidence, review, promotion, rollback, and explicit deployment.
Online adaptation is limited to campaign-local reasoning over current state and approved versioned
priors. This preserves replay and makes regressions attributable.

## 6. Experience-to-Range Compiler

BlackBread's learning moat SHALL include a deterministic or review-gated compiler that converts
repeated real/range failure patterns into de-identified synthetic scenarios and regression fixtures.

It MAY propose:

- terrain and attack-path fixtures;
- stale, conflicting, control-blocked, or partial-evidence cases;
- tool/adapter failure simulations;
- capability compatibility and cleanup scenarios;
- path-value reversal and alternative-strategy benchmarks;
- per-role specialist questions and expected typed outcomes.

It SHALL NOT copy client secrets or identifying content, replay target effects, generate an
executable payload, or self-deploy a test. A range scenario is evidence for engineering improvement,
not evidence about a client.

## 7. Per-role learning

| Role | Learns from | Improves |
|---|---|---|
| Scout | source yield, stale assets, terrain diffs, blind spots, control observations | coverage strategy and next-information choice |
| Strike | oracle discrimination, false applicability, control/tool failure, variant outcomes | proof selection and failure diagnosis |
| Exploit | platform compatibility, delivery, transition, runtime, cleanup outcomes | safest qualified boundary-proof selection |
| Post-Exploit | internal visibility, privilege/trust transitions, bounded movement, objective stops | path construction and minimal-impact objective proof |
| Report | adjudication reversals, client reproduction, remediation/retest path changes | claim calibration, cut sets, remediation leverage, coverage honesty |

Cross-role learning occurs through typed ledger outcomes and promoted experience, never private chain
of thought, arbitrary agent commands, or shared mutable prompt memory.

## 8. Metrics and evaluation

Learning quality SHALL be measured against held-out range/replay campaigns and temporal backtests:

- objective progress and verified path completion;
- information gain per target request and actions per proven edge;
- calibration of applicability and transition beliefs;
- false-positive, false-negative, and inconclusive rates by oracle/evidence family;
- time to abandon dominated paths and recover from failed techniques;
- coverage gain from terrain diffs and alternative paths;
- cleanup, target-health, scope, OPSEC-stop, and authorization violations, whose tolerated value is zero;
- Report downgrades, client reproduction, remediation cut-set accuracy, and retest path elimination;
- cross-tenant leakage or memorization, whose tolerated value is zero.

An improvement in success rate cannot compensate for a safety, authorization, privacy, cleanup, or
evidence-integrity regression.

## 9. First-principles implementation order

1. add `TechniqueOutcome` reason taxonomy before the first real agent action so failures are not lost;
2. persist campaign outcomes through the existing ledger and projections, not a new memory database;
3. expose a read-only, versioned learning snapshot to one named consumer after W3 has produced data;
4. add tenant temporal priors only with consent, isolation, expiry, and revalidation proofs;
5. add global aggregates and the Experience-to-Range Compiler only after privacy and minimum-sample
   gates exist;
6. change a production ranking version only after held-out replay/range evidence and rollback proof.

Schema-first work without a named next-wave consumer is rejected by `ADR-FINAL-004.md`.

## 10. Requirement IDs and gap

| ID | Requirement | State |
|---|---|---|
| `LRN-001` | Task, campaign, tenant, and global memory planes have explicit authority and isolation. | DECIDED |
| `LRN-002` | Every attempted or unattempted opportunity produces a normalized, provenance-bound outcome. | DECIDED |
| `LRN-003` | Failures retain distinct semantics and update only the matching contextual prior. | DECIDED |
| `LRN-004` | Historical experience is advisory, decayed, and never current target truth. | DECIDED |
| `LRN-005` | Learning cannot self-modify or deploy production models, prompts, knowledge, or capabilities. | DECIDED |
| `LRN-006` | Experience can create privacy-safe range/benchmark candidates under review. | DECIDED |
| `LRN-007` | Per-role and campaign learning is measured by held-out objective, evidence, and safety outcomes. | DECIDED |

`LEARNING-GAP-001` in `GAP-REGISTER.md` owns implementation and release status.

## 11. RED-first proof obligations

- a prior-only candidate cannot create a current target fact, graph edge, or report claim;
- campaign, tenant, and global records cannot cross tenant/engagement boundaries;
- Policy denial, model refusal, tool error, control block, negative oracle, and inconclusive evidence
  update distinct reason buckets;
- stale success decays and requires current observation before applicability or transition proof;
- changing only a learning prior cannot change Policy admission for an identical exact effect;
- a model-authored outcome cannot promote its own knowledge definition or capability artifact;
- raw secrets, customer content, screenshots, and identifying evidence are rejected from global data;
- replay with the same ledger and learning version produces the same advisory input;
- a ranking change requires a new immutable version and can be rolled back;
- range generation preserves scenario semantics without client-identifying material.

## 12. Non-claims

This ADR does not implement memory storage, a learning engine, an online model update, a knowledge
registry, an agent, or a range compiler. It does not authorize cross-tenant data reuse, target-facing
execution, autonomous capability promotion, or any claim that BlackBread becomes smarter merely by
recording unqualified outcomes.
