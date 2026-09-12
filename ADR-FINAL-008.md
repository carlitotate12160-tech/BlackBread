# ADR-FINAL-008 — Bounded Lateral Movement

**Status:** ACCEPTED — 2026-09-12; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Post-compromise effect and capability-boundary amendment

**Amends:** `ADR-FINAL-002.md` §§5.2–5.4, 14, 20, 26, 36–40; `ADR-FINAL-003.md` §§6, 11,
13–16; `PRD.md` full-kill-chain mode

**Depends on:** `ADR-FINAL-005.md` through `ADR-FINAL-007.md`

**Primary principle:** Full attack-path proof requires bounded lateral movement; a read capability
must never acquire that effect implicitly.

## 0. Decision

BlackBread SHALL support **bounded lateral movement** in full-kill-chain mode when movement is needed
to prove the campaign-approved objective. The existing rule is clarified: there is
no unrestricted lateral movement, but this is not a ban on every authorized trust transition.

One approved objective MAY require multiple autonomous post-access moves. Approval of the current
campaign authority envelope removes routine per-hop human approval only for effect classes already
inside that envelope; it does not remove exact Policy evaluation, lease issuance, or evidence.

## 1. Dedicated capability boundary

Lateral movement SHALL use a dedicated capability and adapter whose only purpose is one declared
source-to-destination access transition. It SHALL NOT be smuggled through discovery, objective read,
browser navigation, credential validation, cleanup, or a generic target-runtime task.

The objective_read.v1 remains prohibited from performing lateral movement; specifically,
`post_exploit.objective_read.v1` keeps that effect in its prohibited list. A later
registry slice SHALL add separate internal-discovery, privilege-transition, lateral-access-proof,
and objective-proof capabilities only after their individual contracts and release blockers exist.

Each lateral transition requires:

- a current `CampaignAuthorityEnvelope` permitting its effect and destination class;
- one verified source `AccessContext` and one exact destination;
- an eligible, range-qualified, digest-pinned dedicated capability;
- opaque session or secret references bound to the objective and destination;
- a new ActionProposal, exact Policy decision, current lease, and exact `WorkOrder`;
- destination identity and route revalidation at execution time;
- one declared boundary oracle, evidence contract, and cleanup/reconciliation result.

The destination context exists only after evidence promotion. A successful transport or process exit
cannot mint a verified access context by itself.

## 2. Credential and privilege semantics

Post-access identity discovery MAY identify credential or session material necessary to test a
declared path. Raw material SHALL remain inside the Session/Secret Broker or isolated evidence
boundary. Agents receive provenance, applicability, principal, scope, expiry, and opaque handles,
not reusable secrets.

Credential use for movement SHALL be exact-principal, exact-destination, attempt-bounded, and subject
to lockout, MFA, target-health, OPSEC, and cleanup rules. Credential theft-for-keeps, reusable
cross-engagement collections, unrestricted dumping, or bulk harvesting remain forbidden.

Privilege transition proof follows the same model: prove only the minimum context required for the
objective, record the boundary crossed, and stop collecting once the oracle is satisfied.

## 3. Still-prohibited effects

This amendment does not permit:

- autonomous scope or objective expansion;
- broadcast, opportunistic, or worm-like movement;
- persistence, startup installation, durable tokens, or hidden long-term access;
- covert tunnels or general-purpose C2;
- malware, destructive action, ransomware behavior, or production disruption;
- defense disabling, log modification, anti-forensics, or concealment of evidence;
- customer-data collection, bulk exfiltration, or movement after the objective is proved;
- automatic flanking or resume after `BURNED`.

## 4. Evidence and reporting

Every verified lateral edge SHALL reconstruct:

```text
source AccessContext -> exact effect -> destination identity/route
-> boundary oracle -> destination AccessContext -> cleanup state
```

Report distinguishes candidate reachability, attempted movement, control-blocked movement, detected
movement, verified transition, and unassessed branches. A screenshot or graph edge alone is not proof.

## 5. Release gate and non-claims

Lateral movement remains `ON_HOLD` until the external-to-internal range proves source/destination
binding, no scope expansion, secret isolation, attempt limits, cancellation, duplicate prevention,
OPSEC stop, target health, evidence promotion, and cleanup under partial failure.

This ADR does not add a registry entry, activate `post_exploit.objective_read.v1`, or lift R3/R4 release
gates. This ADR does not authorize target-facing execution.
