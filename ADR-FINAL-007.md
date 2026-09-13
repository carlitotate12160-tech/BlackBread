# ADR-FINAL-007 — Ephemeral Target Runtime and Adaptive Capability Synthesis

**Status:** ACCEPTED — 2026-09-12; revised 2026-09-13; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Execution-plane, adaptive-capability, and agentless-footprint amendment

**Depends on:** `ADR-FINAL-005.md`, `ADR-FINAL-006.md`

**Coordinates with:** `ADR-FINAL-009.md`

**Primary principle:** Agentless means no permanent pre-installed BlackBread component; it does not
forbid a short-lived target-side executor after an approved boundary proof.

## 0. Decision

Full-kill-chain mode MAY use an `EphemeralTargetRuntime` when an approved objective cannot be proved
through existing client channels or remote native interfaces alone.

The runtime is a bounded executor. It does not contain an LLM, planner, campaign memory, path ranker,
Policy substitute, or evidence-promotion authority. Cognition remains in the five off-target role
agents. The runtime cannot choose follow-up work.

An authorized off-target LLM MAY adapt parameters, compose a declarative proof recipe, or synthesize
new capability source during a campaign. Its output is always a candidate: it does not become an
executable payload merely because it was generated, compiled, hashed, signed by a build worker, or
judged plausible by another model. Candidate synthesis and target execution are separate trust
domains.

## 1. Admission and identity

The runtime MAY be created only from the single target-effect path:

```text
current campaign authority + exact Policy decision + current lease + exact WorkOrder
-> Capability Gateway -> target-runtime bootstrap -> bounded task -> outcome -> cleanup
```

Creation SHALL require a range-qualified bootstrap capability, fresh target identity, a valid source
access context, an exact destination, an objective binding, target-health and OPSEC admission, an
expiry, and a cleanup/reconciliation obligation.

An existing file, process, session, shell, management agent, or endpoint tool on a target SHALL NOT
be treated as a BlackBread runtime merely because it can execute commands.

## 2. Runtime authority

The runtime MAY:

- authenticate one admitted task and its current lease;
- execute only a digest-pinned module with typed parameters;
- apply time, resource, output, destination, and effect limits;
- capture declared evidence and target-health signals;
- cancel, expire, self-remove, and report cleanup state.

The runtime SHALL NOT:

- expose a generic shell or arbitrary command channel to an agent;
- select, download, generate, mutate, or retry a payload on its own;
- compile source or resolve build dependencies;
- broaden targets, routes, privileges, or capability semantics;
- hold control-plane credentials or give target secrets to an LLM;
- install startup persistence, survive the engagement window, disable controls, or alter logs;
- become a peer-to-peer propagation mechanism.

Its task channel is authenticated, engagement-bound, expiry-bound, and effect-bound. It is
not durable covert C2 and cannot remain available as reusable access after the task or campaign.

## 3. Adaptive capability and payload boundary

This decision does not require a rewrite of the five agents or control plane. They remain in the
current implementation language unless a measured constraint justifies a separate migration. The
target-runtime protocol SHALL be typed, versioned, and language-neutral.

An executable payload is a reviewed capability artifact. Adaptive generation is permitted, but an
LLM output is an **untrusted, non-executable, and non-authorizing** candidate and never reaches a
target directly. The off-target synthesis lane has three classes:

1. **Parameter adaptation:** an agent selects an already eligible capability and emits only values
   allowed by its typed contract. Normal Policy, lease, and `WorkOrder` gates apply.
2. **`CandidateProofRecipe`:** an LLM composes a declarative recipe entirely from already qualified
   primitives inside one registered capability family's declared effects. A deterministic verifier
   proves schema, effect closure, destinations, resource bounds, oracle, cleanup, and negative
   controls before an independent promotion decision.
3. **`CandidateCapabilitySource`:** an LLM may synthesize new source when an existing artifact cannot
   prove the authorized objective. An off-target **Capability Forge** builds it without target
   reachability or target secrets, then static checks, reproducible-build checks, SBOM and provenance
   capture, adversarial fixtures, sandbox/range execution, safety/effect oracles, cleanup tests, and
   independent review decide whether it can be promoted.

The model that authored a candidate cannot be its sole reviewer or promoter. Initially, any new T3
effect, new native executable, unsafe-language boundary, new capability family, or widening of
declared semantics requires human security review. A recipe confined to previously reviewed effects
and qualified primitives MAY use deterministic automated promotion only after that promotion class
itself has passed an accepted implementation and range gate.

Promotion creates an immutable signed artifact. Each artifact SHALL bind its candidate and source
lineage, authoring model and prompt/input snapshot, independent reviews, build provenance, toolchain,
OS/architecture, digest, signature, SBOM, declared effects, resource limits, evidence contract,
cleanup behavior, qualification record, tenant/engagement eligibility, and validity window. A
campaign-local artifact is an instance of an already registered and eligible capability family; its
identity is the family ID plus artifact digest. It cannot add effects, mutate the global registry, or
bypass lifecycle promotion. New semantics or a new family require the ordinary reviewed registry
change. This avoids a catalogue of one payload per CVE without turning the registry into a runtime
LLM write surface.

Public proof-of-concept code and Rapid N-Day intelligence remain untrusted research input. They may
inform a candidate only inside the isolated synthesis lane; they cannot be copied directly into a
target task or self-promote through model agreement, successful compilation, or elapsed time.

If a model refuses an authorized candidate-synthesis request, record typed `MODEL_REFUSAL`. The
owning off-target role and deterministic model router MAY retry once with transparent engagement
authority and a narrower analytical task, route to another approved provider or local model, use a
reviewed deterministic/OSS builder, request human or IDE-assisted development, or choose another
attack path. They SHALL NOT use prompt injection, a jailbreak, identity deception, or hidden-policy
circumvention to force generation.

For future implementation slices:

- retain Python for agent cognition and the control plane;
- evaluate Rust as the preferred default for a small memory-safe target runtime;
- allow Go for isolated network adapters when its deployment and binary footprint are acceptable;
- use C/C++ only where a reviewed native dependency requires it and isolate the unsafe boundary;
- treat Nim and Zig as candidates, not defaults, until their toolchains, libraries, build
  reproducibility, and long-term maintenance pass the same qualification gates.

Language choice never grants capability authority and cannot bypass the Gateway, Policy decision,
lease, `WorkOrder`, evidence, or cleanup contract.

## 4. Evidence

The runtime SHALL produce structured task results, module identity, timestamps, source and
destination context, resource/effect observations, and cleanup evidence. Raw sensitive output is
redacted before it reaches agent cognition; secrets remain opaque Broker references.

A screenshot is supporting evidence and may be captured only when the objective and platform make
it relevant. It SHALL be paired with a declared independent oracle such as a client-seeded marker,
an authenticated read result, a deterministic state check, or a client-side audit event.

## 5. Validity, lifecycle, and recovery

Artifact qualification and task execution use separate clocks:

- `artifact_qualified_until` bounds when the exact artifact remains eligible for admission;
- `lease_expires_at` bounds delegated execution authority;
- `workorder_start_before` is the latest legal dispatch time;
- `execution_deadline` bounds the admitted task runtime;
- `cleanup_deadline` bounds teardown and reconciliation;
- `AccessContext.expires_at` independently bounds the source access fact.

The Conductor SHALL NOT dispatch unless the artifact, source `AccessContext`, decision, and lease are
current and the remaining authority covers the declared worst-case runtime plus cleanup reserve. A
candidate or artifact that becomes stale before dispatch produces a typed stale/expired outcome and
returns to requalification or replanning. Once admitted, the runtime follows the signed task limits
and deadline; it does not compile or mutate a module, extend authority, or substitute an artifact
because a newer CVE record appeared.

The target-runtime lifecycle is `PLANNED -> RANGE_QUALIFIED -> TARGET_APPROVED -> ACTIVE ->
TERMINATING -> RECONCILED`, with failure states for `CANCELLED`, `EXPIRED`, `ORPHANED`, and
`CLEANUP_FAILED`. Candidate and artifact lifecycle is separately
`CANDIDATE -> BUILT -> VERIFIED -> RANGE_QUALIFIED -> PROMOTED -> RETIRED`, with rejection or expiry
at every pre-promotion boundary.

On cancellation, expiry, campaign stop, lease revocation, target instability, or `BURNED`, the
runtime accepts no new tasks and enters teardown. Restart recovery reconstructs orphaned state from
the verified ledger, then revokes or reconciles it; replay never restarts a target task.

Cleanup is successful only after the task channel is closed, temporary modules and artifacts are
removed, sessions are revoked, the target is reconciled, and cleanup evidence is recorded. Intent
to clean is not proof of cleanup.

## 6. Qualification and non-claims

Bootstrap, protocol, module format, Capability Forge, candidate contracts, deterministic verifier,
promotion authority, supported platforms, language choice, and deployment route SHALL be decided and
proved by smaller implementation slices. Every runtime artifact is supply-chain pinned and
range-tested for cancellation, partial failure, cleanup, target health, semantic effect closure, and
platform compatibility before client eligibility.

This ADR does not implement a Capability Forge or target runtime, approve a bootstrap or model,
admit or promote a target capability, authorize zero-day research against a client, or permit
persistence or C2. This ADR does not authorize target-facing execution.
