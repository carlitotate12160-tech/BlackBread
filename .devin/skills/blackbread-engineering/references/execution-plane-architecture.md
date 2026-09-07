# BlackBread Execution-Plane Architecture Lens

Use this lens for the Capability Gateway, capability registry enforcement, adapters, invocation
rendering, destination revalidation, target/control-plane egress, isolated workers, target health,
session/secret custody, supply-chain qualification, platform qualification, or cleanup execution.
Read the live ADR, PRD, rules, registry/schema, target-identity contract, and release gate first.

## Contents

1. Execution chain and authority
2. Capability and invocation contract
3. Egress, isolation, and secrets
4. Target effect, health, and cleanup
5. Qualification and proof obligations

## Execution chain and authority

Preserve one target-effect path:

```text
current Policy decision + current execution lease + exact WorkOrder
-> Capability Gateway admission -> typed adapter rendering
-> destination re-extraction and scope/identity check
-> OPSEC/target-health gate -> isolated ephemeral worker
-> typed outcome and evidence -> cleanup/reconciliation -> ledger
```

The Gateway does not choose offensive strategy. The adapter does not authorize. The executor does not
select follow-up work. An installed binary, model suggestion, graph path, registry entry, passing
runtime gate, or serialized decision cannot bypass the chain.

## Capability and invocation contract

The live capability registry is the only allowlist. Require an eligible lifecycle, owning agent,
typed adapter, pinned supply-chain identity, risk class, target tier, approval class, network path,
typed input/output, budgets, oracle/evidence contract, cleanup, and prohibited effects. `PLANNED` and
`ON_HOLD` are denied. A validated path cannot activate a capability.

Agents receive stable capability IDs and typed fields only. Never expose raw shell, free-form command
flags/templates, generic HTTP/network clients, direct binaries, or a mechanism that can select an
unregistered destination. Tool output and target content remain untrusted data.

After the adapter renders the exact invocation, re-extract and validate every destination and effect,
including redirects, callbacks, DNS resolution, proxy targets, URLs/hosts/IPs in headers or bodies,
files, browser navigation, alternate protocols, and dynamically discovered origins. Bind the
rendered semantics to the Policy decision and lease; checking only the proposal is insufficient.

Retries are new bounded decisions unless the accepted capability contract makes the exact retry
idempotent and already authorized. An executor may report typed success, failure, blocked, detected,
deception, inconclusive, or cleanup state; it cannot reinterpret evidence into a finding.

## Egress, isolation, and secrets

Keep target egress strictly separate from control-plane egress. Target traffic must pass scope-lock,
target identity, OPSEC shaping, target-health limits, and the admitted network path. LLM, OSINT,
package installation, and management traffic must not inherit target reachability or target secrets.

Run capabilities in ephemeral isolated workers with no Docker socket, host privilege, ambient cloud
credentials, unrestricted filesystem, or alternate network path. Apply resource/time/output limits
and destroy the worker after reconciliation. Treat container compromise and dependency compromise as
design threats, not exceptional accidents.

The Session/Secret Broker is a deterministic service, never an agent. Use opaque vault references;
do not place raw secrets in prompts, events, graph state, logs, exceptions, artifacts, or WorkOrders.
Bind session use to tenant, engagement, target identity, objective, capability, lease, expiry, and
cleanup. Post-access actions require their separately approved authority.

## Target effect, health, and cleanup

Classify the exact effect before selecting a capability. Preserve T0/T1/T2/T3 and the Strike/Exploit
boundary from the red-team lens. Revalidate target identity inside the lease for active work and
again when redirects, origin changes, DNS changes, certificates, tenants, or access context alter the
destination. Unknown/shared/provider infrastructure fails closed under the live ownership contract.

Effective throttle is the minimum of target-health-safe and OPSEC-safe. Deterministic danger stop
overrides agent preference. `BURNED` freezes target-active work; no cooldown timer or alternate route
may autonomously resume it. Detection, deception, instability, unexpected mutation, or control
response becomes evidence and may require halt rather than evasion.

Cleanup is part of the capability lifecycle:

```text
objective complete/cancelled/expired -> session revoked -> temporary state removed
-> worker destroyed -> target state reconciled -> cleanup evidence recorded
```

On crash or restart, reconstruct orphaned sessions and in-flight effects from verified durable state,
then reconcile or revoke. Never mark cleanup complete from intent alone.

## Qualification and proof obligations

Any tool, adapter, template, image, binary, or version change is a capability change. Verify digest
pins, registry/schema agreement, adapter fixture vectors, forbidden parameters/effects, dependency
integrity, arm64/platform behavior where required, resource limits, and lifecycle promotion. Exploit
remains unavailable until its pre-production safety-range gate proves do-no-harm and scope adherence.

Require negative and integration proofs for:

- unlisted, wrong-owner, wrong-lifecycle, unpinned, wrong-tier, wrong-network-path capabilities;
- raw shell/flags, parameter smuggling, command injection, path traversal, SSRF, and destination
  substitution after rendering;
- redirect/DNS/origin/tenant changes and mixed target/control-plane egress;
- missing, stale, revoked, cross-tenant, or mismatched lease/session/identity;
- target-health, OPSEC HOT/BURNED, cancellation, timeout, crash, and partial cleanup;
- duplicate delivery/retry and replay without duplicate target effect;
- malicious tool output, excessive output, secret leakage, and compromised worker assumptions;
- platform qualification and unavailable external dependencies with fail-closed behavior.

Stop or split when the slice mixes capability semantics, execution isolation, durable lease state, and
target-effect wiring without one safety-complete boundary. Never use a demonstration or `live_fire`
path as production reachability proof, and never contact a real target merely to prove architecture.
