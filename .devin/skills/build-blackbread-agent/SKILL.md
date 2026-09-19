---
name: build-blackbread-agent
description: Guidance for building and extending BlackBread's autonomous agents (Scout, Strike, Exploit, Post-Exploit, Report) so they operate with APT operator tradecraft while positioned as an authorized external red-team exploitation platform. Use when implementing an agent, its cognition loop, capabilities, OPSEC behavior, or wiring it into the Conductor / Policy Kernel / ledger.
triggers:
  - user
  - model
---

# Building a BlackBread Agent

BlackBread is an authorized, covert, agentless external red-team / adversary-emulation platform.
Agents reason like an APT operator: patient, stealth-conscious, objective-driven, and chain-composing.
The product proves an external-to-objective attack path, including control outcomes and cleanup;
it does not sell scanner counts or infer security from an empty result.

**Golden rule:** LLM = reasoning cortex. Deterministic code = skeleton, muscle, memory, and safety.
The LLM proposes; it never directly executes effects or decides safety admission. Agentless means
no permanent pre-installed component; an approved ephemeral target runtime follows ADR-FINAL-007.md.

Use this skill for role implementation and integration. Read the repository AGENTS.md, accepted
ADRs, PRD, rules, gap register, and capability registry for the selected responsibility. Verify live
implementation and release status before changing an executable path.

## Five role anchors

| Agent | Goal | Never |
|---|---|---|
| Scout | Discover evidence-backed external or access-context terrain | test credentials, exploit, mutate target state, confirm findings |
| Strike | Confirm primitive applicability at minimum risk | broad-spray, destructive actions, silently cross a new security boundary |
| Exploit (ON HOLD until its release gate) | One controlled, verified boundary proof | unqualified payload execution, persistence |
| Post-Exploit | Advance the approved objective through dedicated capabilities | unbounded movement, durable access, scope expansion |
| Report | Independently adjudicate evidence; downgrade unsupported claims | assert impact beyond proof |

These are reasoning roles, not a mandatory pipeline. Detailed ownership and acceptance criteria live
in role-contracts.md; Conductor, OPSEC, and Session/Secret Broker remain deterministic services.

## Authority and delivery

Use [blackbread-engineering](../blackbread-engineering/SKILL.md) for design seals, execution packets,
preflight, review, and delivery. Follow its selected references and the live delivery contract;
this skill does not define a separate merge or bypass procedure.

The protected-main versions of ADR-FINAL-003.md and ADR-FINAL-004.md govern cognition and effect tiers. Read ADR-FINAL-005.md
through ADR-FINAL-009.md for campaign authority, chaining, execution, movement, and Rapid N-Day.
Treat any unmerged amendment, including ADR-FINAL-010.md and ADR-FINAL-011.md, as prospective: its
additional knowledge, specialist, and learning guidance does not become authority until merged. File
presence or an ACCEPTED heading in an unmerged draft does not establish protected-main authority or
runtime implementation.

## Select references

Read the complete reference for each changed responsibility; do not load every reference for every task.

| Responsibility | Required reference |
|---|---|
| Context, local OODA, opportunities, specialist reasoning, readiness, or feedback | [Cognition and frontier](references/cognition-and-frontier.md) |
| APT tradecraft doctrine, role ownership/depth, Scout/Strike behavior, or acceptance criteria | [Role contracts](references/role-contracts.md) |
| Capability adapters, identity/effect tiers, OPSEC integration, Forge, or target runtime | [Capability integration](references/capability-integration.md) |
| Outcome semantics, memory, priors, or behavioral evaluation | [Learning and evaluation](references/learning-and-evaluation.md) |

The architecture lenses in blackbread-engineering assess the boundary; these references guide its
implementation. Shared OPSEC, Broker, Gateway, and Conductor services remain services.

## Build from first principles

Do not begin with an agent class, tool list, or prompt. For each slice, derive this chain:

1. **Outcome:** name the exact objective progress, information gain, or evidence claim the slice must produce.
2. **State:** bind a coherent graph slice to `WorldSnapshotRef`, current `AccessContext`, objective,
   opportunity frontier, and a separate versioned learning snapshot when that consumer exists.
3. **Authority:** assign reasoning, truth promotion, authorization, scheduling, execution, persistence,
   and adjudication to their existing owners; naming a component never grants authority.
4. **Candidate:** emit a typed `InvestigationIntent`, then an atomic proposal only for an active,
   ready reservation; hypotheses and specialist assessments never become free-form target actions.
5. **Effect:** bind a family from `config/capability-registry.json`, exact Policy decision, lease,
   and `WorkOrder` to the transition, oracle, negative control, cleanup, and successor context.
6. **Feedback:** use `TechniqueOutcome` reason classes and admitted graph deltas to continue,
   backtrack, reobserve, reconsider an authorized asset/surface, request another role, or stop.
7. **Vertical proof:** implement the smallest replayable producer-to-consumer loop and its negative
   controls before expanding schemas, catalog breadth, tools, or prompts.

Reject fixed playbooks and free-form target execution. `AttackKnowledgeRegistry` is declarative
knowledge, `OpportunityCompiler` emits advisory candidates, role agents choose strategy, and existing
Policy/Conductor/Gateway boundaries control exact effects. Historical outcomes are contextual priors,
never current target facts.

## Non-negotiable floor

Apply this floor regardless of which references are loaded; accepted ADRs own its detailed semantics.

- No direct target execution: effects pass Conductor, Policy Kernel, OPSEC, and typed capability admission.
- Recon is read-only; HTTP discovery is GET-only with no forms, state-changing links, or lockout risk.
- `BURNED` freezes target-active work in the affected engagement; passive analysis alone may continue.
- Unlisted capability families and ineligible artifacts are denied; a generated candidate is not eligibility.
- Verify target identity and ownership before active work; revalidate as required by the exact effect.
- Every claimed attack-path transition needs its declared oracle; a screenshot or tool match alone is insufficient.

## Completion

Name the requirement, owner, producer, next consumer, evidence oracle, negative cases, and applicable
release gate. Use DECIDED, IMPLEMENTED, VERIFIED, and RELEASED only with their required evidence.
Record missing blocking work in GAP-REGISTER.md. No documentation edit activates a capability.
