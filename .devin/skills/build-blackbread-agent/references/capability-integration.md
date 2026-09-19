# Capability Integration

Authority: ADR-FINAL-003.md §§14–15, ADR-FINAL-004.md §3, and ADR-FINAL-005.md through ADR-FINAL-009.md.
Read this reference for tools, identity, effects, OPSEC, candidate qualification, and target runtime.

## Contents

- Target identity and effect tiers
- Capabilities and tools
- OPSEC integration
- Post-access runtime and payloads
- Vulnerability currency

## Target identity and effect tiers

Bind evidence to hostname/IP/certificate/application/tenant/time and verify ownership. Use the
ADR-003/004 effect meanings: T0 passive/offline, T1 active read-only, T2 sensitive validation,
and T3 controlled boundary/impact proof. Origin-direct is a route, not the definition of T2.
Independently validate origin identity, destination, and route; enforce the identity assurance and
freshness required by the admitted effect, including fresh validation inside the T3 lease.
Do not silently reinterpret sealed v1 contracts; any contract migration is a separately reviewed slice.

Derive approval from the engagement mode, campaign envelope, capability, and exact effect. The
campaign envelope removes routine per-hop human approval only for effects it expressly includes.
Policy, lease, WorkOrder, lifecycle, OPSEC, and cleanup admission still apply.

## Capabilities & tools
- Every tool runs behind a typed Capability Gateway contract and must exist in `config/capability-registry.json`. The registry, not an agent prompt or an installed binary, defines ownership and eligibility.
- Select a capability by the proof it can produce, not by brand. The entry must declare owner, adapter, pinned version/digest, lifecycle, risk, Target Identity Guard tier, approval, network path, typed I/O, budget, oracle/evidence, cleanup, and prohibited effects.
- Agents receive a capability ID and typed fields only. Never expose shell, free-form flags/templates, generic HTTP/network clients, or direct binaries. After the adapter renders an invocation, re-extract and scope-check every destination before execution.
- Scout owns passive/T1 terrain discovery; restricted Strike owns offline/T1 verification for Recon-only; full Strike owns approved T2 validation; Exploit owns T3 controlled boundary proof but remains ON HOLD; Post-Exploit owns objective-bound internal reasoning and dedicated access-transition proposals; Report uses offline evidence/report tooling and requests re-verification through the Conductor. Every target effect remains subject to its campaign envelope, exact Policy decision, lease, and `WorkOrder`.
- Customize OSS at extension points (Nuclei templates, mitmproxy addons, sqlmap tamper scripts); build-fresh the small high-value pieces (DNS resolver/brute, CT-log consumer, passive-source resilience layer). Prefer JSON/library output over CLI scraping.
- Browser: utls/curl-impersonate fast path; Camoufox heavy path (cap concurrency). Never build a browser engine.
- A tool/template/version change is a capability change: pin it, rerun fixture and negative controls, qualify arm64 behavior, and promote lifecycle explicitly. `PLANNED`/`ON_HOLD` entries never execute.

## OPSEC service (deterministic danger-stop)
- Extract suspicion signals per response (WAF blocks/challenges, 429/`Retry-After`, resets, latency/tarpit, soft-blocks, honeytoken hits, new WAF, White Cell escalation).
- Heat FSM `COOL → WARM → HOT → BURNED`; throttle = min(health-safe, OPSEC-safe).
- Jitter: log-normal delays + Poisson arrivals + circadian shaping + burst-idle + AIMD backoff + token buckets + order shuffle; avoid uniform patterns (self-signature).
- **The LLM cannot override the hard stop.** BURNED freezes target-active work and notifies the operator/White Cell. Only passive analysis continues; any active recovery requires operator approval, fresh target identity, and a new lease.
- De-signature all tool traffic centrally (browser-like UA/header order/**TLS JA3**/HTTP2 + pacing) via the egress proxy; controlled evasion is loose-on-form / strict-on-effect.

## Post-access runtime and payloads

Agentless means no permanent pre-installed BlackBread component. When an approved boundary proof
requires target-side execution, an `EphemeralTargetRuntime` may execute one digest-pinned module from
an exact `WorkOrder`; it has no LLM, planner, generic shell, follow-up selection, persistence, or
durable covert C2. It must expire, reconcile, remove temporary artifacts, and record cleanup evidence.

An LLM may adapt typed parameters, compose a `CandidateProofRecipe`, or synthesize a
`CandidateCapabilitySource` during a campaign. Its untrusted output never reaches a target directly.
Candidate generation runs off-target without target reachability or secrets. A Capability
Forge performs deterministic verification, isolated reproducible builds, provenance/SBOM capture,
adversarial fixtures, range qualification, cleanup proof, and independent promotion. The authoring
model cannot be the sole reviewer or promoter; new T3/native effects initially require human security
review. Only an immutable signed artifact inside an eligible registry family can enter Policy,
lease, `WorkOrder`, Gateway, and target-runtime admission.

Bind campaign-local artifacts to tenant, engagement, capability family, exact digest, effects,
platform, qualification record, and `artifact_qualified_until`. Separately enforce
`AccessContext.expires_at`, `lease_expires_at`, `workorder_start_before`, `execution_deadline`, and
`cleanup_deadline`; do not dispatch without worst-case runtime plus cleanup reserve. The target
runtime never compiles, mutates, retries, or selects a replacement module.

Keep the agent/control plane in Python unless measured constraints justify change; evaluate Rust for
a small target runtime, Go for isolated network adapters, and C/C++ only behind reviewed native
boundaries. Nim and Zig are candidates only after reproducible toolchain and maintenance
qualification. Language choice grants no capability authority.

Only bounded lateral movement is permitted: an objective-bound source-to-destination transition
implemented by a dedicated capability. It requires a verified source `AccessContext`, exact
destination and route, new atomic proposal, Policy decision, lease, `WorkOrder`, boundary oracle,
and cleanup result.
`post_exploit.objective_read.v1` remains prohibited from performing movement.

## Vulnerability currency

Rapid N-Day separates public intelligence from execution. Vendor/CVE records may be enriched with
NVD, KEV, and EPSS, but public exploit code remains untrusted research input. No advisory, score,
public PoC, model assessment, or elapsed disclosure time may promote or activate a capability.
Dedicated zero-day hunting and weaponization are outside the product; an accidental novel candidate
halts increased invasiveness and enters the human-owned disclosure process.
