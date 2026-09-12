# ADR-FINAL-007 — Ephemeral Target Runtime

**Status:** ACCEPTED — 2026-09-12; becomes repository authority only when merged

**Implementation status:** DECIDED only

**Decision class:** Execution-plane and agentless-footprint amendment

**Depends on:** `ADR-FINAL-005.md`, `ADR-FINAL-006.md`

**Primary principle:** Agentless means no permanent pre-installed BlackBread component; it does not
forbid a short-lived target-side executor after an approved boundary proof.

## 0. Decision

Full-kill-chain mode MAY use an `EphemeralTargetRuntime` when an approved objective cannot be proved
through existing client channels or remote native interfaces alone.

The runtime is a bounded executor. It does not contain an LLM, planner, campaign memory, path ranker,
Policy substitute, or evidence-promotion authority. Cognition remains in the five off-target role
agents. The runtime cannot choose follow-up work.

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
- broaden targets, routes, privileges, or capability semantics;
- hold control-plane credentials or give target secrets to an LLM;
- install startup persistence, survive the engagement window, disable controls, or alter logs;
- become a peer-to-peer propagation mechanism.

Its task channel is authenticated, engagement-bound, expiry-bound, and effect-bound. It is
not durable covert C2 and cannot remain available as reusable access after the task or campaign.

## 3. Technology and payload boundary

This decision does not require a rewrite of the five agents or control plane. They remain in the
current implementation language unless a measured constraint justifies a separate migration. The
target-runtime protocol SHALL be typed, versioned, and language-neutral.

An executable payload is a reviewed capability artifact, not arbitrary agent-generated code. Each
artifact SHALL bind its source and build provenance, toolchain, OS/architecture, digest, signature,
SBOM, declared effects, resource limits, evidence contract, cleanup behavior, and qualification
record. The LLM selects only an eligible capability and typed parameters; it never emits code into
the target execution path.

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

## 5. Lifecycle and recovery

The lifecycle is `PLANNED -> RANGE_QUALIFIED -> TARGET_APPROVED -> ACTIVE -> TERMINATING ->
RECONCILED`, with failure states for `CANCELLED`, `EXPIRED`, `ORPHANED`, and `CLEANUP_FAILED`.

On cancellation, expiry, campaign stop, lease revocation, target instability, or `BURNED`, the
runtime accepts no new tasks and enters teardown. Restart recovery reconstructs orphaned state from
the verified ledger, then revokes or reconciles it; replay never restarts a target task.

Cleanup is successful only after the task channel is closed, temporary modules and artifacts are
removed, sessions are revoked, the target is reconciled, and cleanup evidence is recorded. Intent
to clean is not proof of cleanup.

## 6. Qualification and non-claims

Bootstrap, protocol, module format, supported platforms, language choice, and deployment route SHALL
be decided and proved by smaller implementation slices. Every runtime artifact is supply-chain
pinned and range-tested for cancellation, partial failure, cleanup, target health, and platform
compatibility before client eligibility.

This ADR does not implement a target runtime, approve a bootstrap method, admit a target capability,
or permit persistence or C2. This ADR does not authorize target-facing execution.
