# BlackBread Red-Team Architecture Lens

Use this lens for changes to agent roles, campaign reasoning, evidence, target identity, finding
semantics, authorization meaning, control assessment, or target-effect classification. It is not a
generic penetration-testing playbook. Read the relevant live sections of `ADR-FINAL-002.md`,
`ADR-FINAL-003.md`, `PRD.md`, the gap register, and the capability registry before applying it.

## Contents

1. Product and mission boundary
2. Role and authority separation
3. World and claim semantics
4. Authorization and effect tiers
5. Evidence and reporting
6. Design gate and rejected shortcuts

## Product and mission boundary

Preserve BlackBread's exact category:

```text
service: authorized external red-team exploitation
method: threat-informed adversary emulation
posture: objective-driven, covert, agentless, least-invasive, evidence-backed
excluded: malware, durable target persistence, covert C2, destruction,
          anti-forensics, indiscriminate exploitation, credential theft-for-keeps
```

Evaluate every domain change against the mission chain:

```text
external observation -> candidate primitive -> applicability validation
-> controlled proof -> access context -> separately approved impact objective
-> defensive-control assessment -> cleanup
```

Do not collapse the chain. A scanner match, version match, leaked credential, graph edge,
screenshot, login, absent alert, or empty result does not independently prove the next stage.

## Role and authority separation

Maintain five bounded cognition domains and no central Mission Brain:

| Role | Owns | Must never silently become |
| --- | --- | --- |
| Scout | Evidence-backed terrain and information gaps | Credential tester, exploit validator, or finding authority |
| Strike | Minimum-risk applicability validation | Boundary-crossing Exploit through retry or escalation |
| Exploit | One approved, verifiable boundary proof; remains ON HOLD until its release gate | General-purpose attack agent or persistence mechanism |
| Post-Exploit | One separately approved impact objective | Open-ended access exploration or collection |
| Report | Independent evidence adjudication and client-legible claims | Execution authority or private truth rewriter |

Agents may propose hypotheses, path assessments, information gaps, bounded intents, and typed action
proposals. They cannot mutate canonical truth, approve scope, promote evidence, allocate budgets,
issue locks or leases, command another agent, or execute. Cross-role work travels through typed events
and deterministic readiness/reservation contracts. Agreement count is not an oracle.

## World and claim semantics

Keep the ADR-FINAL-003 views separate and coherently bound to one verified ledger prefix and time:

| View | Answers | Does not prove |
| --- | --- | --- |
| CyberTerrainGraph | What exists and which trust/control structures shape reachability | Applicability, exploitability, authorization, or objective progress |
| AttackPathGraph | Which candidate or verified offensive transitions may advance an objective | Permission to execute or capability eligibility |
| ControlAssessmentProjection | What defensive effect was tested and observed | Absence of the underlying condition |
| CampaignProjection | Objective-relative progress, bounded work, stalls, and alternatives | Target truth or hidden strategic authority in Conductor |
| CampaignBlackboard | Immutable coherent composition of views | Mutable canonical storage or LLM memory authority |

Preserve truth-class separation among observations, hypotheses, strategic assessments, policy
decisions, execution outcomes, and promoted verified facts. Ledger presence proves that BlackBread
recorded an event; it does not prove the event's target claim.

Controls are terrain and evidence, not noise. Distinguish external blocking, tested control effect,
underlying application condition, customer test exception, and actual adversarial control bypass.
`WAF blocked` is not `not vulnerable`; customer allowlisting is not a bypass proof.

## Authorization and effect tiers

Keep target identity, capability lifecycle, claim maturity, and action authorization on independent
axes:

- T0 passive observations may create candidates, not active reachability.
- T1 active read-only observations may validate terrain or low-risk preconditions.
- T2 approved validation may establish applicability or control effect, not a new security context.
- T3 boundary or impact proof requires fresh identity inside a current lease, an eligible capability,
  current policy/OPSEC facts, approval, cleanup, and the applicable release gate.

A Strike success condition must not establish a new privilege, authentication, authorization, trust,
execution, or isolation boundary. If success requires one, classify it as Exploit/T3 and create a new
proposal. Never let repeated validation self-upgrade into exploitation.

Controlled evasion remains loose on form and strict on effect: the rendered semantics must map to an
authorized, reviewed, non-destructive base action. OPSEC subtlety never expands scope or effect.

## Evidence and reporting

Require a named, versioned, digest-bound oracle; target-identity binding; temporal validity; source
lineage; required independent evidence families; and a negative control before promotion. Two tools
using the same source lineage are not independent. Model confidence, votes, screenshots without an
independent oracle, and structural reachability do not promote a claim.

Report may accept, narrow, downgrade, request evidence, or reject. Preserve proven and unproven impact,
cleanup state, coverage limitations, control effects, and inconclusive branches. `Nothing found` is
never `secure`, and detection by the client is a defensible outcome to report.

## Design gate and rejected shortcuts

For each change, answer:

```text
Which role owns the reasoning?
Which deterministic component owns truth promotion?
Which target tier and capability lifecycle apply?
What exact effect or claim changes?
Which oracle and independent evidence establish it?
Can the change bypass Policy, OPSEC, lease, cleanup, or Report adjudication?
Does a control observation preserve the underlying evidence separately?
Can a candidate, hypothesis, or path become fact or execution merely by serialization?
```

Reject designs that introduce a Mission Brain, strategic Conductor, mutable LLM blackboard, agent
commands, model voting as truth, terrain-to-exploitability shortcuts, WAF-blocked-as-safe semantics,
client-exception-as-bypass claims, Strike escalation until success, unbounded investigation fan-out,
or an executable path from a probabilistic assessment.

Proof must include the applicable ADR-FINAL-003 RED-first cases: view coherence, advisory isolation,
promotion integrity, reservation deduplication, state-axis separation, path-value reversal, local
disagreement, Strike/Exploit boundary, control distinction, Report independence, tenant isolation,
and capability-state independence. Use only the subset touched by the slice and justify the rest as
N/A rather than loading unrelated work.
