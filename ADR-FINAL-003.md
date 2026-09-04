# ADR-FINAL-003 — Campaign Intelligence, Verified Terrain, and Bounded Investigation

**Status:** ACCEPTED — 2026-09-04; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Foundational architecture amendment

**Amends:** `ADR-FINAL-002.md` §§6, 9, 10, 21, 24, 25, 28, 32, 35, and 36

**Retains:** every authorization, Policy Kernel, OPSEC, target-identity, capability,
evidence-integrity, do-no-harm, agentless-execution, and release gate in `ADR-FINAL-002`

**Central cognition:** None

**Central control:** Deterministic Conductor + Policy Kernel + OPSEC

**Canonical record:** Append-only hash-chained Event Ledger

**Primary principle:** Centralized safety, decentralized cognition, evidence-governed truth

## 0. Decision

BlackBread SHALL remain a five-agent decentralized-cognition system:

- Scout
- Strike
- Exploit
- Post-Exploit
- Report

There SHALL be no Mission Brain and no autonomous central strategist. Local OODA loops remain owned
by the five role agents. Cross-agent campaign coherence SHALL be provided by a deterministic,
ledger-derived campaign protocol, not by hidden LLM memory and not by strategic reasoning inside the
Conductor.

The shared read model SHALL be an immutable `CampaignBlackboard` assembled from one coherent
`WorldSnapshotRef`:

```
              Signed objective + verified ledger prefix
                           |
                           v
                    WorldSnapshotRef
                           |
        +------------------+------------------+
        |                  |                  |
        v                  v                  v
CyberTerrainGraph  AttackPathGraph  ControlAssessmentProjection
        \                 |                  /
         +----------------+-----------------+
                           |
                           v
                    CampaignProjection
                           |
                           v
                    CampaignBlackboard
                           |
        +------------------+------------------+
        | Scout | Strike | Exploit | Post-Exploit | Report |
        +------------------------------------------+
```

`CampaignBlackboard` SHALL NOT be independently mutable storage. Agents read it and publish typed
events. Deterministic projectors rebuild it from the verified ledger prefix.

The execution authority chain is unchanged:

```
Agent reasoning -> ActionProposal -> Policy Kernel -> Conductor
  -> WorkOrder + Lease -> bounded executor -> evidence -> Event Ledger
```

Core invariant:

> Reasoning recommends. Promotion rules admit claims. Policy authorizes. Conductor coordinates.
> Executors act. Evidence determines what may be asserted.

## 1. Failure-pattern decision

The existing ADR correctly forbids a central brain and gives every agent a local OODA loop, but it
does not fully define campaign-level coordination. Without this amendment, locally competent agents
can produce globally incoherent behavior:

- duplicate investigations over the same unchanged state;
- oscillation between roles or paths;
- local optimization that ignores a better objective path;
- a blocked path consuming work after its information value is exhausted;
- attack-path claims inferred from mere terrain reachability;
- defensive-control observations overwriting evidence about the underlying condition;
- mixed projection versions creating a state that never existed at one ledger prefix.

The original research direction is accepted, but its first draft is corrected here because it also
introduced three new failure modes:

- `OPSEC_HOLD`, `WAITING_RESOURCE`, and `POLICY_STOP` were incorrectly placed inside a progress
  enum even though they are readiness conditions, not evidence of stall.
- `CampaignState` included LLM strategic assessments while also claiming to be deterministic
  epistemic truth.
- independent terrain, attack, control, and campaign version integers permitted torn reads and
  target-state substitution.

This ADR keeps these concepts on separate authority and state axes.

## 2. Separation of authorities

### Agents

Agents MAY:

- propose hypotheses and information gaps;
- assess objective relevance, information gain, cost, risk, and OPSEC noise;
- request a bounded investigation reservation;
- emit an `ActionProposal` after a reservation is ready;
- challenge, narrow, or reject prior reasoning.

Agent assessments are advisory and SHALL NOT directly mutate epistemic truth, authorization,
readiness, budgets, leases, or objective state.

### Evidence Promotion Service

The Evidence Promotion Service SHALL be deterministic. It validates that a requested promotion:

- names a versioned, digest-bound oracle;
- supplies every required evidence family;
- satisfies freshness and target-identity requirements;
- includes the required negative control;
- does not count shared source lineage as independent evidence;
- is valid for the named `ClaimKind` transition.

It does not invent evidence or interpret business impact.

### Policy Kernel

The Policy Kernel remains the only authority that decides whether an exact rendered action may
execute. Campaign priority, agent confidence, graph reachability, and model agreement cannot bypass
policy.

### Conductor

The Conductor MAY coordinate reservations, readiness, dependencies, fair resource scheduling,
budgets, locks, leases, cancellation, and cleanup. It SHALL NOT calculate offensive path value,
invent hypotheses, select techniques, infer impact, or change objectives.

When several ready investigations compete for a constrained resource, the Conductor SHALL apply a
versioned non-strategic scheduling rule based only on policy class, readiness, reservation age,
fairness, conflict locks, and remaining hard budgets. It SHALL NOT use LLM confidence or offensive
utility as hidden authorization.

### Executors

Executors perform one exact bounded invocation and cannot choose follow-up work.

### Report

Report remains an autonomous evidence-adjudication role. It MAY publish `ACCEPT`, `NARROW`,
`DOWNGRADE`, `REQUEST_EVIDENCE`, or `REJECT` assessments. A Report assessment is an input to the
promotion/disclosure contract; it is not direct authority to rewrite evidence or execute work.

## 3. Canonical record and truth classes

The Event Ledger is the canonical record of what BlackBread received, proposed, decided, executed,
and observed. Not every ledger event is a fact about the target.

Every event payload SHALL declare exactly one truth class:

- `EVIDENCE_OBSERVATION`
- `HYPOTHESIS`
- `STRATEGIC_ASSESSMENT`
- `POLICY_DECISION`
- `ORCHESTRATION_STATE`
- `PROMOTION_DECISION`
- `REPORT_ASSESSMENT`

Only admitted evidence and deterministic promotion decisions may contribute to verified terrain,
verified attack transitions, or objective progress. A hypothesis or strategic assessment remains
canonical as a recorded statement, but never becomes canonical target truth merely because it is in
the ledger.

LLM agreement is reasoning diversity, not evidence independence.

## 4. Coherent projection bundle

Cyber terrain, attack paths, control assessments, and campaign progress SHALL be separate
deterministic views over one verified ledger prefix. They SHALL NOT use separate canonical databases.

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


HexDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(ge=1, le=9_223_372_036_854_775_807)]
NonNegativeInt = Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
Ratio = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
BoundedCost = Annotated[float, Field(ge=0.0, le=1_000_000.0, allow_inf_nan=False)]


def require_canonical_tenant_id(value: str) -> str:
    if not value or value != value.strip() or "\x00" in value:
        raise ValueError("tenant_id must be canonical non-blank text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("tenant_id contains invalid Unicode") from exc
    return value


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


CanonicalTenantId = Annotated[
    str, AfterValidator(require_canonical_tenant_id), Field(max_length=100)
]
CanonicalUtcTimestamp = Annotated[datetime, AfterValidator(require_utc)]
CapabilityStyleId = Annotated[
    str,
    Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\.v[1-9][0-9]*$",
        max_length=200,
    ),
]
SchemaRef = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*\.v[1-9][0-9]*$")]
IdentityTier = Literal["T0", "T1", "T2", "T3"]
AgentRole = Literal["Scout", "Strike", "Exploit", "Post-Exploit", "Report"]
InvestigationAgentRole = Literal["Scout", "Strike", "Exploit", "Post-Exploit"]
EpistemicState = Literal[
    "OBSERVED",
    "CANDIDATE",
    "VALIDATION_PENDING",
    "VALIDATED",
    "CROSS_VERIFIED",
    "REJECTED",
    "INCONCLUSIVE",
    "SUPERSEDED",
]
ClaimKind = Literal[
    "EXPOSURE",
    "APPLICABILITY",
    "AUTHENTICATION",
    "AUTHORIZATION",
    "CONTROL_EFFECT",
    "BOUNDARY",
    "IMPACT",
]


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LedgerAnchorRef(FrozenStrictModel):
    verified_event_count: PositiveInt
    verified_head_hash: HexDigest


class ProjectionRef(FrozenStrictModel):
    projection_name: Literal["cyber_terrain", "attack_path", "control_assessment", "campaign"]
    schema_version: PositiveInt
    projector_version: PositiveInt
    state_root_version: PositiveInt
    state_root: HexDigest


class WorldSnapshotRefV1(FrozenStrictModel):
    schema_name: Literal["world.snapshot_ref"]
    schema_version: Literal[1]
    tenant_id: CanonicalTenantId
    engagement_id: UUID
    as_of: CanonicalUtcTimestamp
    ledger_anchor: LedgerAnchorRef
    terrain: ProjectionRef
    attack_path: ProjectionRef | None
    control_assessment: ProjectionRef | None
    campaign: ProjectionRef | None

    @model_validator(mode="after")
    def _projection_name_matches_slot(self) -> Self:
        slots = {
            "terrain": "cyber_terrain",
            "attack_path": "attack_path",
            "control_assessment": "control_assessment",
            "campaign": "campaign",
        }
        for slot, expected in slots.items():
            ref = getattr(self, slot)
            if ref is not None and ref.projection_name != expected:
                raise ValueError(
                    f"{slot} must contain a ProjectionRef with projection_name={expected!r}"
                )
        return self
```

Rules:

- Every present `ProjectionRef` SHALL be computed from the exact parent `ledger_anchor` and `as_of`.
- Each state-root preimage SHALL include tenant, engagement, `as_of`, ledger anchor, projection name,
  schema version, projector version, state-root version, and canonical projection content.
- A view from another tenant, engagement, time, or ledger prefix fails closed.
- Missing optional views are explicit unavailability, never an empty successful result.
- A consumer SHALL declare the minimum required views. T2/T3 work cannot silently fall back to a
  terrain-only snapshot.
- `ActionProposal` v1 and its digest remain byte-stable. A future `ActionProposal` v2 may replace its
  `GraphVersionReference` with `WorldSnapshotRefV1`; it SHALL NOT reinterpret the v1 preimage.

## 5. CyberTerrainGraph

CyberTerrainGraph answers:

> What exists, how is it connected, and which trust or defensive structures shape reachability?

Representative node families:

- ScopeRoot, Host, Address, DNSName, Service, Certificate, Application,
  Route, API, Identity, Tenant, Network, CloudResource, DataResource,
  SecurityControl, TrustBoundary, BusinessAsset

Representative relation families:

- `RESOLVES_TO`, `PRESENTS`, `HOSTS`, `EXPOSES`, `ROUTES_TO`, `AUTHENTICATED_BY`,
  `PROTECTED_BY`, `TRUSTS`, `CONNECTED_TO`, `SEGMENTED_BY`, `BELONGS_TO`,
  `REACHABLE_FROM`, `DEPENDS_ON`

Terrain reachability SHALL NOT imply exploitability, authorization, applicability, boundary
crossing, or objective progress. Terrain entities and relations retain epistemic state, target
identity, temporal validity, source evidence, producer, and supersession.

The current M1 ScopeRoot temporal projection is a trust-spine scope projection. It SHALL NOT be
misrepresented as a completed CyberTerrainGraph or AttackPathGraph merely because its package is
named `graph` or because NetworkX can render it.

## 6. AttackPathGraph

AttackPathGraph answers:

> Which candidate or verified offensive transitions could move an approved objective forward?

Representative semantic families:

- Primitive, Precondition, AccessContext, Boundary, TrustTransition, Impact, Objective

Representative relation families:

- `ENABLES`, `SATISFIES_PRECONDITION`, `CROSSES_BOUNDARY`, `GRANTS_CONTEXT`,
  `LEADS_TO`, `PROVES`

An attack-path edge SHALL:

- reference stable `CyberTerrainGraph` entity IDs instead of copying terrain entities;
- carry one `ClaimKind` and one `EpistemicState`;
- reference a versioned oracle and admitted evidence;
- declare temporal validity and target-identity binding;
- identify its exact source and destination security contexts;
- declare whether crossing it requires T0, T1, T2, or T3 authority.

Candidate, rejected, inconclusive, or superseded edges SHALL NOT satisfy an objective, unlock a
capability, or appear in a verified client attack path.

## 7. Control representation

Control existence/topology and control effectiveness are different claims.

A WAF, CDN, identity provider, proxy, firewall, or segmentation boundary exists as a
`CyberTerrainGraph` entity/relation.

A tested effect exists as a `ControlAssessment` in `ControlAssessmentProjection`.

```python
class ControlAssessment(FrozenStrictModel):
    assessment_id: UUID
    control_entity_id: HexDigest
    protected_entity_ids: tuple[HexDigest, ...]
    test_mode: Literal["EXTERNAL_REALITY", "CONTROL_VALIDATION", "APPLICATION_ASSURANCE"]
    outcome: Literal[
        "EFFECTIVE_FOR_TESTED_CASE",
        "FAILURE_PROVEN",
        "COVERAGE_GAP_PROVEN",
        "PARTIAL_COVERAGE",
        "NOT_EVALUATED",
        "INCONCLUSIVE",
    ]
    client_test_exception_ref: UUID | None
    underlying_claim_ref: UUID | None
    oracle_ref: OracleDefinitionRefV1
    evidence_refs: tuple[UUID, ...]
    based_on_snapshot: WorldSnapshotRefV1
    valid_from: CanonicalUtcTimestamp
    valid_until: CanonicalUtcTimestamp

    @model_validator(mode="after")
    def _application_assurance_requires_exception(self) -> Self:
        if self.test_mode == "APPLICATION_ASSURANCE" and self.client_test_exception_ref is None:
            raise ValueError("APPLICATION_ASSURANCE requires client_test_exception_ref")
        return self
```

- `CLIENT_TEST_EXCEPTION_ACTIVE` SHALL NOT be transformed into `CONTROL_BYPASS_PROVEN`.
- `EFFECTIVE_FOR_TESTED_CASE` SHALL NOT erase an independently validated underlying condition.
- `test_mode=APPLICATION_ASSURANCE` requires `client_test_exception_ref`; the exception is test
  context, not a control outcome.

## 8. Epistemic, claim, and disclosure state

The draft's single linear promotion ladder is rejected because boundary proof, impact, and
reportability are different dimensions.

### Epistemic state

- `OBSERVED`
- `CANDIDATE`
- `VALIDATION_PENDING`
- `VALIDATED`
- `CROSS_VERIFIED`
- `REJECTED`
- `INCONCLUSIVE`
- `SUPERSEDED`

### Claim kind

- `EXPOSURE`
- `APPLICABILITY`
- `AUTHENTICATION`
- `AUTHORIZATION`
- `CONTROL_EFFECT`
- `BOUNDARY`
- `IMPACT`

### Disclosure state

- `NOT_REPORTABLE`
- `REPORT_CANDIDATE`
- `REPORTABLE`
- `WITHHELD_BY_POLICY`

`PROVEN_BOUNDARY` means `ClaimKind=BOUNDARY` plus an oracle-approved epistemic state. It is not a
universal step that every observation traverses. `IMPACT_VERIFIED` is defined similarly.

Promotion without required provenance, evidence-family independence, negative control, freshness,
or target identity SHALL fail closed.

## 9. Versioned oracle contract

An unversioned UUID or prose string is insufficient for an evidence-critical oracle.

```python
class OracleDefinitionRefV1(FrozenStrictModel):
    oracle_id: CapabilityStyleId
    oracle_digest: HexDigest


class OracleDefinitionV1(FrozenStrictModel):
    schema_name: Literal["evidence.oracle_definition"]
    schema_version: Literal[1]
    ref: OracleDefinitionRefV1
    claim_kind: ClaimKind
    evaluation_mode: Literal["DETERMINISTIC", "INDEPENDENT_MEASUREMENT", "REPORT_ADJUDICATION"]
    required_evidence_family_ids: tuple[CapabilityStyleId, ...]
    minimum_independent_families: PositiveInt
    positive_condition_schema_ref: SchemaRef
    negative_condition_schema_ref: SchemaRef
    inconclusive_condition_schema_ref: SchemaRef
    freshness_seconds: PositiveInt
    minimum_target_identity_tier: IdentityTier
    negative_control_required: bool
```

Oracle definitions SHALL be registry-loaded, digest-pinned, immutable by version, and default-denied
when missing or mismatched. Model confidence cannot substitute for an oracle result.

## 10. CampaignProjection and advisory assessments

`CampaignProjection` is deterministic and objective-relative. It MAY contain:

- objective progress derived from admitted promotion decisions;
- open and closed information gaps;
- active and terminal hypotheses;
- path prefixes supported by admitted evidence;
- investigation reservations and trajectories;
- stall and exhaustion state;
- policy, resource, and OPSEC readiness state by reference.

It SHALL NOT calculate offensive utility or convert an LLM assessment into objective truth.

Strategic assessments are exposed beside the projection as an advisory feed:

```python
class PathAssessmentV1(FrozenStrictModel):
    assessment_id: UUID
    producer_agent_instance_id: UUID
    producer_role: AgentRole
    objective_ref: UUID
    path_ref: UUID
    based_on_snapshot: WorldSnapshotRefV1
    objective_relevance: Ratio
    expected_information_gain: Ratio
    estimated_cost: BoundedCost
    estimated_risk: Ratio
    estimated_opsec_noise: Ratio
    recommendation: Literal[
        "CONTINUE", "DEEPEN_INFORMATION", "DEFER", "ABANDON", "REQUEST_OTHER_ROLE"
    ]
    rationale_artifact_ref: UUID
    created_at: CanonicalUtcTimestamp
    expires_at: CanonicalUtcTimestamp
```

Assessments remain producer-attributed, snapshot-bound, expiring, and advisory. They can explain why
an agent proposed work, but cannot directly satisfy a precondition or grant readiness.

## 11. Bounded investigation and orthogonal state

One `InvestigationTrajectory` investigates exactly one hypothesis or information goal.

```python
class InvestigationTrajectoryV1(FrozenStrictModel):
    trajectory_id: UUID
    tenant_id: CanonicalTenantId
    engagement_id: UUID
    owner_agent_instance_id: UUID
    owner_role: InvestigationAgentRole
    hypothesis_ref: UUID
    objective_ref: UUID
    based_on_snapshot: WorldSnapshotRefV1
    goal: Literal[
        "CLOSE_INFORMATION_GAP",
        "TEST_HYPOTHESIS",
        "VALIDATE_PRECONDITION",
        "PROVE_BOUNDARY",
        "VERIFY_IMPACT",
    ]
    capability_allowlist: tuple[CapabilityStyleId, ...]
    step_budget: PositiveInt
    action_budget: NonNegativeInt
    cost_budget: BoundedCost
    oracle_ref: OracleDefinitionRefV1
    lifecycle: Literal["PROPOSED", "ACTIVE", "SUCCEEDED", "REJECTED", "INCONCLUSIVE", "ABORTED"]
    progress: Literal["UNEXPLORED", "ADVANCING", "STALLED", "EXHAUSTED"]
    readiness: Literal[
        "READY",
        "WAITING_EVIDENCE",
        "WAITING_RESOURCE",
        "OPSEC_HOLD",
        "POLICY_STOP",
        "ENGAGEMENT_STOPPED",
    ]
    observation_refs: tuple[UUID, ...]
    termination_reason_code: CapabilityStyleId | None
```

State-axis invariants:

- `OPSEC_HOLD`, `WAITING_RESOURCE`, and `WAITING_EVIDENCE` do not increment stall counters.
- `STALLED` requires attempted work with no meaningful state delta under otherwise-ready conditions.
- `EXHAUSTED` is terminal for the current hypothesis/path version, not for the objective.
- A material snapshot change may create a new trajectory; it SHALL NOT silently reset the old one.
- Repeating the same capability, target, parameters, oracle, and relevant snapshot requires a typed
  justification and remaining retry budget.
- Report uses an `EvidenceAdjudicationCase`, not an offensive investigation trajectory.
- Meaningful progress is limited to new admitted evidence, a closed information gap, a disproven
  hypothesis, a validated precondition, a newly proven relationship, objective advancement, or material
  uncertainty reduction recognized by the applicable oracle.

## 12. Hypothesis lineage

Every hypothesis SHALL have reconstructible origin:

```python
class HypothesisV1(FrozenStrictModel):
    hypothesis_id: UUID
    tenant_id: CanonicalTenantId
    engagement_id: UUID
    origin: Literal[
        "OBSERVATION",
        "INFORMATION_GAP",
        "PARENT_HYPOTHESIS",
        "TERRAIN_RELATION",
        "VALIDATED_CLAIM",
        "AGENT_INFERENCE",
    ]
    parent_refs: tuple[UUID, ...]
    reasoning_type: Literal[
        "INITIAL", "VARIANT", "ANALOGY", "PRECONDITION", "ALTERNATIVE_PATH", "CONTROL_GAP"
    ]
    claim_kind: ClaimKind
    target_entity_refs: tuple[HexDigest, ...]
    based_on_snapshot: WorldSnapshotRefV1
    producer_agent_instance_id: UUID
    evidence_refs: tuple[UUID, ...]
    epistemic_state: EpistemicState
    created_at: CanonicalUtcTimestamp
    expires_at: CanonicalUtcTimestamp
```

Private agent notes may inspire a hypothesis but cannot be its durable origin. The published object
must identify the ledger-visible observation, gap, parent, terrain relation, claim, or attributed
agent inference that caused it.

## 13. Decentralized campaign coordination protocol

The shared blackboard alone does not coordinate a campaign. BlackBread SHALL implement this protocol:

```python
class InvestigationIntentV1(FrozenStrictModel):
    intent_id: UUID
    tenant_id: CanonicalTenantId
    engagement_id: UUID
    producer_agent_instance_id: UUID
    producer_role: InvestigationAgentRole
    objective_ref: UUID
    hypothesis_ref: UUID
    goal: Literal[
        "CLOSE_INFORMATION_GAP",
        "TEST_HYPOTHESIS",
        "VALIDATE_PRECONDITION",
        "PROVE_BOUNDARY",
        "VERIFY_IMPACT",
    ]
    target_entity_refs: tuple[HexDigest, ...]
    capability_family_ref: CapabilityStyleId
    oracle_ref: OracleDefinitionRefV1
    based_on_snapshot: WorldSnapshotRefV1
    requested_step_budget: PositiveInt
    requested_action_budget: NonNegativeInt
    requested_cost_budget: BoundedCost
    deduplication_key: HexDigest
    created_at: CanonicalUtcTimestamp
    expires_at: CanonicalUtcTimestamp
```

An agent reads one `CampaignBlackboard` bound to one `WorldSnapshotRef`.

The agent publishes a typed hypothesis, path assessment, or information gap.

The agent publishes one `InvestigationIntent` with a canonical deduplication key over engagement,
objective, hypothesis, goal, target set, capability family, oracle, and world snapshot.

The deterministic Conductor admits at most one active reservation for the same deduplication key,
checks dependency/readiness state, and applies non-strategic fairness and resource scheduling.

The owning agent may emit an `ActionProposal` only for an active reservation.

Policy evaluates the exact proposal. A reservation is not execution permission.

Evidence and outcome events update deterministic projections.

Agents re-read a new coherent blackboard snapshot before further reasoning.

No agent may command another agent. `REQUEST_OTHER_ROLE` is an advisory event. The requested role
independently accepts or rejects it according to its own contract and the current blackboard.

If agents disagree, BlackBread records both assessments. It does not vote them into truth. Duplicate
reservations are suppressed; resource allocation remains fair and deterministic; strategic quality is
measured by campaign benchmarks. Persistent failure of this protocol is evidence for a future
Campaign Advisor ADR, not permission to hide strategy inside the Conductor.

## 14. Strike and Exploit effect boundary

Strike validates whether a candidate is genuine, applicable, and sufficiently supported. A Strike
success oracle SHALL NOT require establishing a new privilege, authorization, authentication, trust,
execution, or isolation boundary.

If the required positive condition crosses such a boundary, the proposal is an Exploit proposal and
requires the corresponding T3 identity, approval, capability lifecycle, lease, risk, OPSEC, and cleanup
contracts. Strike cannot increase invasiveness until success; escalation creates a new proposal.

Exploit remains ON HOLD under `ADR-FINAL-002` until the R3 safety-range gate is released.

## 15. Target-identity and capability placement

- **T0:** passive observations may enrich candidate terrain with source provenance. They do not
  establish active reachability or an attack transition.
- **T1:** active read-only observations may validate terrain relations or low-risk preconditions when
  the applicable oracle succeeds.
- **T2:** approved validation may produce applicability or control-effect claims. It does not prove a
  boundary crossing unless reclassified and approved as T3.
- **T3:** controlled boundary/impact proof requires a fresh target-identity check inside the lease and
  a current complete `WorldSnapshotRef` required by policy.

Capability lifecycle state remains independent from graph or campaign state. A validated path cannot
promote a `PLANNED` or `ON_HOLD` capability to executable eligibility.

## 16. Milestone and release placement

This ADR does not alter the active M1.4 sequence and does not authorize target-facing behavior.

| Milestone / release | Required addition | State on ADR acceptance |
|---|---|---|
| M1 / R0 | Finish Policy Kernel, ledgered decisions, leases, Conductor, and kill switch. Preserve `ActionProposal` v1. | Existing work continues |
| M2 | Versioned oracle registry; typed evidence/promotion contracts; capability registry uses digest-bound oracle refs. | DECIDED |
| M3 | `CyberTerrainGraph`, coherent `WorldSnapshotRef`, hypotheses, trajectories, reservations, and minimal `CampaignProjection`/blackboard for Scout. | DECIDED |
| M4 | `AttackPathGraph`, `ControlAssessmentProjection`, promotion enforcement, Strike/Exploit effect boundary, cross-role feedback. | DECIDED |
| M5 / R1 | Report adjudication integration and campaign-coherence benchmark suite over Scout -> restricted Strike -> Report. | DECIDED; blocks R1 until verified |
| M6 | Durable low-and-slow pause/resume, stale assessment expiry, replay-safe reservation recovery, and long-horizon campaign metrics. | DECIDED |

`CAMPAIGN-GAP-001` SHALL be recorded as P1, target M3-M5, blocking R1 but not M1/R0 or M1.4b.

### Normative gap entry

**CAMPAIGN-GAP-001 — Campaign coherence and coherent multi-view world snapshot are not implemented**

- **Status:** OPEN
- **Severity:** P1 architecture
- **Owner:** campaign-intelligence
- **Target milestone:** M3-M5
- **Blocks:** R1 and every target-facing release
- **Current evidence:** agents have only local OODA contracts; the live M1 projection contains temporal
  `ScopeRoot` nodes and zero attack edges; no `CampaignProjection`, `CampaignBlackboard`,
  `CyberTerrainGraph`/`AttackPathGraph` separation, `WorldSnapshotRef`, trajectory reservation protocol,
  or campaign-coherence benchmark exists on the live path.
- **Required closure:** implement and wire `CAM-001` through `CAM-005`, `GRF-001` through `GRF-002`,
  `EVD-001`, `CTL-001`, `AGT-001`, and `REP-006` through the milestone order in this ADR.
- **Verification:** the RED-first contract in §18 plus the R1 Scout -> restricted Strike -> Report
  campaign-coherence conformance record.
- **Compensating control:** no target-facing release is eligible; M1/R0 may continue because the current
  deny-only trust spine cannot execute target actions.

## 17. Requirement IDs

| ID | Requirement | State |
|---|---|---|
| `CAM-001` | `CampaignBlackboard` is an immutable composite view, never mutable canonical storage. | DECIDED |
| `CAM-002` | `CampaignProjection` is deterministic and cannot promote advisory assessments into truth. | DECIDED |
| `CAM-003` | Investigation trajectories are bounded and use orthogonal lifecycle/progress/readiness state. | DECIDED |
| `CAM-004` | Cross-agent work uses typed intents, deterministic reservations, deduplication, and non-strategic scheduling. | DECIDED |
| `CAM-005` | Campaign coherence is tested and the no-central-brain decision remains falsifiable. | DECIDED |
| `GRF-001` | `CyberTerrainGraph` and `AttackPathGraph` are separate deterministic views with no reachability-to-exploitability shortcut. | DECIDED |
| `GRF-002` | All campaign views bind to one ledger anchor and `as_of` through `WorldSnapshotRef`. | DECIDED |
| `EVD-001` | Evidence promotion uses versioned digest-bound oracles, evidence-family independence, freshness, target identity, and negative controls. | DECIDED |
| `CTL-001` | Control topology and tested control effect remain separate; controls cannot erase underlying evidence. | DECIDED |
| `AGT-001` | Strike cannot use a boundary-crossing success condition; such work is Exploit/T3. | DECIDED |
| `REP-006` | Report can narrow or reject upstream conclusions but cannot directly authorize action or rewrite evidence. | DECIDED |

No ID is `IMPLEMENTED`, `VERIFIED`, or `RELEASED` merely because this ADR is accepted.

## 18. RED-first verification contract

Implementation SHALL begin with focused tests that fail for the intended missing behavior.

| Proof obligation | RED test must demonstrate | Must NOT pass because |
|---|---|---|
| Snapshot coherence | mixed terrain/attack ledger anchors are rejected | equal integer versions do not prove the same ledger prefix |
| Replay determinism | identical verified ledger + `as_of` yields identical view roots and blackboard | projection creation time or mutable LLM state cannot affect output |
| Terrain/attack separation | a `REACHABLE_FROM` terrain relation creates no attack transition | reachability is not applicability or exploitability |
| Advisory isolation | a high-confidence `PathAssessment` cannot satisfy a precondition or objective | model belief is not evidence or authorization |
| Promotion integrity | missing oracle digest, evidence family, negative control, freshness, or target identity rejects promotion | provenance-free success is false success |
| State-axis integrity | `OPSEC_HOLD` and `WAITING_RESOURCE` do not mark a path stalled | no work opportunity existed from which lack of progress could be inferred |
| Reservation dedup | equivalent intents on the same snapshot yield one active reservation | independent reasoning is not permission for duplicate target work |
| Material-change retry | unchanged semantic action is rejected without typed justification and retry budget | another tool call is not progress |
| Path-value reversal | after admissible evidence changes A/B conditions, new agent intents move toward B and A stops consuming work | Conductor must not rank offensive paths or hide a strategist |
| Local disagreement | competing agent assessments do not oscillate or become truth by vote | agreement count is not an oracle |
| Strike/Exploit boundary | a Strike oracle requiring a new security-context boundary is rejected | validation cannot silently self-upgrade into exploitation |
| Control distinction | external blocking retains the validated underlying condition and records control effect separately | WAF-blocked is not not-vulnerable |
| Client exception | an application-assurance exception cannot produce `CONTROL_BYPASS_PROVEN` | a sanctioned test condition is not an adversarial bypass |
| Report independence | Report can narrow/reject a producer claim and the producer cannot force acceptance | evidence producer and adjudicator are separate authorities |
| Tenant isolation | any cross-tenant entity, edge, assessment, hypothesis, or trajectory reference fails closed | no campaign object can bridge tenants |
| Capability independence | a verified path cannot execute a `PLANNED`, `ON_HOLD`, mismatched-agent, or unpinned capability | graph state cannot mutate capability admission |

Campaign coherence benchmark scenarios SHALL include path-value reversal, stalled path, false
hypothesis, information-gap feedback, control-blocked condition, client test exception, OPSEC hold,
local planner disagreement, restart/replay, and duplicate-intent suppression.

## 19. Explicitly rejected designs

- Mutable LLM blackboard.
- One Mission Brain.
- Conductor as strategist or path-value ranker.
- Separate canonical databases for terrain, attack paths, controls, and campaign state.
- Several unbound projection version integers in one decision.
- Model voting as evidence.
- Terrain reachability as an attack edge.
- WAF blocked as proof that the underlying condition is absent.
- Client test exception as adversarial bypass.
- Strike escalating until success.
- Unbounded investigation fan-out.
- A linear epistemic ladder that mixes claim type, confidence, and reportability.

## 20. Future Campaign Advisor

No Campaign Advisor is authorized by this ADR.

A separate ADR MAY propose one only after benchmark evidence shows repeatable local-optimum traps,
dominated-path persistence, cross-role oscillation, excessive duplicate work, or poor objective
progress despite competent local agents and a correct coordination protocol.

A future advisor may compare paths and recommend continue, deepen, defer, or abandon. It may never
authorize, execute, issue a work order or lease, change scope or policy, override OPSEC, mutate
canonical truth, or become required for fail-safe operation.

## 21. Final architecture statement

BlackBread is a five-agent, decentralized-cognition, objective-driven external red-team platform over
an immutable evidence ledger and coherent deterministic campaign projections.

Cyber terrain describes the environment. Attack paths describe candidate or verified offensive
transitions. Control assessments describe tested defensive effects. Campaign projection describes
objective-relative progress and bounded work state. The blackboard assembles those views at one
verified ledger prefix. Agents reason locally and publish typed intent. Oracles and promotion rules
govern claims. Policy authorizes. Conductor coordinates. Executors act. Report independently judges
what can be said.

No probabilistic reasoning component may convert its own belief directly into execution authority,
canonical target truth, or a client-facing verified claim.
