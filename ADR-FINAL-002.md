# ADR-FINAL-002 — BlackBread: Agentless Autonomous External Red-Team / Adversary-Emulation Platform

- **Status:** Accepted — 2026-08-27; supersedes all prior BlackBread architecture drafts
- **Implementation status:** M0 foundation only; acceptance of this decision does not claim that later milestones are implemented or production-eligible
- **Decision class:** Foundational architecture
- **Product type:** Authorized autonomous external red-team exploitation, operated with adversary-emulation (APT) tradecraft
- **Primary vantage:** External, black-box, unauthenticated at engagement start
- **Operating posture:** Covert (stealth) — the client's blue team is not informed; only a designated White Cell knows
- **Target execution model:** Agentless; no permanent platform implant
- **Architecture:** Five autonomous role agents + deterministic central orchestration + shared deterministic services
- **Agents:** Scout, Strike, Exploit, Post-Exploit, Report (Anchor dissolved into a Session/Secret Broker service + a Scout access-context module)
- **Central cognition:** None
- **Central control:** Deterministic Conductor + Policy Kernel + OPSEC service
- **Canonical state:** Append-only, hash-chained event ledger (PostgreSQL)
- **World state:** Temporal, evidence-backed attack graph (PostgreSQL projection; NetworkX rebuilt on demand)
- **Execution:** Typed capabilities through ephemeral isolated workers, behind a single controlled egress gateway
- **Controlled evasion:** First-class, SOW-authorized capability — "loose on form, strict on effect"
- **Persistence / destructive actions / real anti-forensics:** Prohibited by default
- **Initial infrastructure:** Python 3.12, PostgreSQL, Docker Compose, single Oracle Cloud ARM VM (12 GB RAM / 4 OCPU), local encrypted artifacts + off-box encrypted backup
- **Initial commercial exit:** One cross-verified, evidence-backed payable finding on an authorized real target, delivered as the "Recon-only" product tier

---

## 0. Authority, Conformance, and No-Blocking-Debt Contract

This ADR is the canonical architecture decision for BlackBread. It is **accepted as a decision**;
implementation readiness is tracked separately and must be demonstrated by source, tests, and release
evidence. A statement in a document never proves that a capability exists.

When artifacts conflict, authority is resolved in this order:

1. applicable law, the executed SOW, and the signed engagement manifest;
2. accepted ADR decisions and hard safety invariants in this document;
3. `PRD.md` requirements and release acceptance criteria;
4. `.devin/rules/blackbread.md` engineering enforcement rules;
5. machine-readable capability registry and schemas;
6. `.devin/skills/build-blackbread-agent/SKILL.md` implementation guidance;
7. `TEST-AUDIT.md`, README files, examples, and historical material.

Lower-authority artifacts may make a higher-authority rule stricter, but may not weaken, silently
reinterpret, or mark it complete. Agent-Alpha is historical input only and has no authority over
BlackBread. Comparisons and lessons from it belong in historical/audit material, not active contracts.

Every architecture requirement has four independent states:

- `DECIDED`: this ADR defines the required behavior.
- `IMPLEMENTED`: the live autonomous path contains the behavior.
- `VERIFIED`: automated tests prove the behavior and its negative cases.
- `RELEASED`: the relevant release gate records evidence and approves operational use.

Only release evidence may claim `RELEASED`. Missing work must be recorded as an explicit gap with a
stable ID, severity, owner, target milestone, blocking release, verification test, and closure evidence.
`TODO`, `TBD`, `later`, `dormant`, skipped tests, `continue-on-error`, and undocumented manual waivers
may not hide release-blocking work. A blocker can be deferred only by an accepted ADR amendment that
states the compensating control and the release at which it becomes mandatory.

Each milestone is a hard dependency gate. Work for the next milestone may be prototyped, but the
release cannot advance while any current or inherited `P0`/`P1`, safety, authorization, scope,
tenant-isolation, evidence-integrity, or cleanup blocker remains open. CI validates contract drift;
branch protection makes the CI checks required; neither can be bypassed by an agent or ordinary PR.

---

## 1. Decision Summary

BlackBread is an **autonomous, threat-informed, external red-team / adversary-emulation platform**. It answers a client's question — *"can a real external attacker reach my approved objective, and would I detect them?"* — by operating like an APT operator (patient, stealthy, objective-driven, chain-composing) while remaining strictly authorized, non-destructive, and agentless.

The platform uses **five autonomous domain agents**:

- **Scout** — discovers external primitives across the full authorized surface (web *and* non-web).
- **Strike** — confirms whether a primitive is genuine, applicable, and usable, at minimum risk.
- **Exploit** — produces one controlled, approved, independently verifiable boundary-crossing proof (exploit phase **on hold** until the platform is proven stable).
- **Post-Exploit** — proves one separately approved impact objective after access.
- **Report** — independently verifies evidence and builds the client-legible report.

Each agent owns a local goal, a role-specific planner and critic, working memory, a capability portfolio, local stop conditions, and a typed output contract. There is **no central Mission Brain**.

**Anchor is dissolved.** Its two mixed responsibilities are separated:
- the **Session/Secret Broker** becomes a deterministic trust-spine *service* (never an autonomous agent);
- the **access-context reasoning** becomes a *module inside Scout*, activated when authenticated testing begins.

Deterministic control is provided by the **Conductor**, the **Policy Kernel**, and the **OPSEC service**. They enforce authorization, scope, budgets, resource locks, execution leases, stealth pacing, and cleanup — without choosing offensive strategy.

Agents never send arbitrary commands to each other. All collaboration flows through:

```
typed event → event ledger → graph projection → Conductor work-readiness → work order → target agent
```

---

## 2. Positioning & Category

Two labels describe BlackBread and are complementary, not contradictory:

- **Service category:** *external red-team exploitation* — it proves exploitability, not just detects surface.
- **Methodology:** *adversary emulation* — it is threat-informed and emulates APT tactics, techniques, and mindset, covertly and objective-driven.

"Positioned as external red-team exploit, but works like an APT" **is** the definition of adversary emulation: the service is red-team, the *method* is APT-like.

**Distinction from neighbors:**
- **Penetration test** — breadth, noisy, announced, maximize vuln count. BlackBread differs: objective-driven and covert.
- **BAS (Breach & Attack Simulation)** — canned scenarios, installed agents, own environment. BlackBread differs: agentless, external, real-target, novel findings.
- **ASM (Attack Surface Management)** — stops at "here is your surface." BlackBread continues to validate and prove.
- **Autonomous pentest tools** — closest neighbor; BlackBread's differentiators are covert APT tradecraft, evidence discipline, and the agentless footprint.

**Honest scope nuance:** BlackBread is **threat-informed emulation**, not "pure" MITRE adversary emulation. It borrows discipline and TTPs (recon breadth, identity/trust reasoning, chain composition, patience, stealth) but **excludes** malware, real persistence, covert C2, destructive actions, and anti-forensics. The accurate one-liner: *"Autonomous, threat-informed, external red-team / adversary-emulation platform."*

---

## 3. Mission

BlackBread must build the chain:

```
external observation → candidate primitive → validation → access opportunity
→ controlled proof → access context → approved post-access objective
→ impact proof → defensive-control assessment → cleanup
```

It must never assume:

```
scanner match = finding            version match = exploitable
credential leak = valid credential graph path = proven path
screenshot = independent oracle    successful login = authorization weakness
no alert = undetected              no finding = secure
```

---

## 4. Product Principles

1. **Authorization before autonomy.** An agent works only after a machine-readable, attested engagement contract exists.
2. **Five agents, five responsibilities.** No central brain overrides local cognition.
3. **Objective over tool completion.** Actions are chosen by information gap, not by an unrun-tool checklist.
4. **Proof over claims.** Every finding needs evidence and a precise oracle.
5. **Chain thinking.** Each primitive is judged by what it proves, its next precondition, the boundary it may open, capability, risk, cost, and cleanup.
6. **Patient but bounded.** Agents re-plan and switch paths but cannot retry without limit.
7. **Agentless footprint.** No permanent platform component on the target.
8. **Centralized safety, decentralized cognition.** Agents think; policy and stealth math stay deterministic and central.
9. **Learn, do not self-rewrite.** Agents improve through sanitized data, not by editing their own code or permissions.
10. **Coverage honesty.** "No vulnerability found" is never "proven secure."
11. **Stealth as discipline.** BlackBread stays quiet by default, adapts when suspected, and treats getting caught as a client win to report.
12. **Least-invasive proof.** Prefer exposure + applicability + a safe oracle over risky exploitation; escalate invasiveness only when the oracle demands it and it is approved.
13. **Deterministic danger-stop, cognitive sneakiness.** The LLM chooses *how* to be subtle; deterministic services decide *when to stop*.

---

## 5. Threat-Informed Doctrine (APT References)

Four threat groups are used as **discipline references**, not as sources of malware, covert persistence, or evasion-for-harm playbooks. Under BlackBread's covert posture, controlled evasion and low-and-slow patience are adapted within the authorization and do-no-harm boundaries below.

### 5.1 APT41 — initial-access breadth
- **Adapted:** never rely on one vulnerability class; keep multiple independent entry hypotheses; match capability to real target context; prioritize exposed, reusable primitives; rapid applicability assessment.
- **Lanes:** CVE exposure, credential exposure, secret exposure, configuration exposure, authorization weakness, cloud exposure, external trust boundary, public artifact, **edge/VPN appliance exposure**, **exposed network services**.
- **Not adapted:** third-party supply-chain compromise, indiscriminate exploitation, malware deployment, infrastructure abuse.

### 5.2 APT29 — identity, trust, patience, and stealth
- **Adapted:** identity graph; trust-boundary reasoning; client-mediated authentication; credential provenance; role/tenant binding; **patient, low-and-slow collection**; strict access/post-access separation; alternate-path planning.
- **Not adapted:** token theft for durable access, covert cloud persistence, concealed long-term access, unauthorized identity manipulation.

### 5.3 Lazarus — chain composition
- **Adapted:** `primitive → precondition → boundary → next primitive → objective`, with a dedicated oracle per graph edge.
- **Not adapted:** financial theft, destructive operations, malware chains, bulk collection, covert exfiltration.

### 5.4 Volt Typhoon — environment awareness and living-off-the-land
- **Adapted:** environment classification; understanding available services; minimal added tooling; native read-only capabilities; post-access trust mapping; segmentation verification; **stealth / low-noise behavior**.
- **Not adapted:** persistence, credential extraction for keeps, log manipulation / anti-forensics, defense disabling.

**Controlled evasion clause:** BlackBread performs authorized evasion of WAF/CDN/rate-limit and honeypot-avoidance to emulate a capable attacker. Evasion is bounded by scope, the Policy Kernel, do-no-harm, and a reviewed technique library. It is **loose on form (encoding/obfuscation/pacing), strict on effect (semantics map to a reviewed non-destructive base)**.

---

## 6. High-Level Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Operator · White Cell (designated client users only)      │
│ Web checklist + attestation → signed engagement manifest  │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│ Conductor + Policy Kernel + OPSEC service                 │
│ Scope · Policy · Budgets · Locks · Leases · Heat · Pacing │
└───────────────────────────┬──────────────────────────────┘
                            │ typed work orders
        ┌──────────┬────────┼────────┬──────────────┐
        ▼          ▼        ▼        ▼              ▼
      Scout      Strike   Exploit  Post-Exploit   Report
    (+access-  (+cred    (ON HOLD)                (independent
     context)   intel)                             verifier)
        │          │        │        │              │
        └──────────┴────────┴───┬────┴──────────────┘
                                ▼
                   Capability Gateway  ── Session/Secret Broker service
                                │              Deception module · Vuln-Intel
                                ▼
              Single controlled OPSEC egress gateway
              (destination scope-lock · TLS/JA3 shaping · jitter)
                                │
                   Ephemeral isolated workers
                                │
                                ▼
           Hash-chained Event + Evidence Ledger (PostgreSQL)
                                │
                     Graph Projectors → NetworkX (rebuildable)
                                │
                                ▼
                    Shared Verified World Model
                                │
              ┌─────────────────┴──────────────────┐
              ▼                                     ▼
        Agent-local views                   Continuous Report
```

Two egress paths are **strictly separated**: (1) **target egress** — scope-locked and stealth-shaped, through the OPSEC gateway; (2) **control-plane egress** — LLM APIs, passive OSINT sources, package installs — normal, never through the target gateway.

---

## 7. Separation of Authorities

### 7.1 Agents
May reason, hypothesize, propose, critique, select candidate capabilities, reject work, request evidence, publish outcomes.
May not authorize themselves, change scope, issue their own lease, change global budget, bypass a denial, disable logging, mutate policy, execute arbitrary shell, or promote a private hypothesis directly into fact.

### 7.2 Conductor
May create engagements, validate manifest-derived policy, receive proposals, validate schemas, issue work orders, serialize conflicting actions, issue/revoke leases, enforce budgets, halt execution, invoke cleanup, and update lifecycle state.
Does not invent hypotheses, choose techniques, interpret findings, generate payloads, or decide business impact.

### 7.3 Policy Kernel (crown jewel)
Pure deterministic function, **fail-closed**, **un-bypassable** (the only path from proposal to execution):

```
decision = f(engagement policy, target identity, capability,
             ALL action parameters, approval, budget, locks, heat)
```

- **Deep destination validation:** extract *every* host/IP/URL from *all* parameters (callbacks, proxies, body-embedded) and scope-check each against the allowlist and exclusions — defeats target substitution, SSRF-from-our-own-agent, and injection-driven exfil.
- **Risk-class gating:** passive → auto; active-read-only → lease; mutating/exploit/post-exploit → approval-required — each mapped to a Target Identity Guard tier (T1/T2/T3).
- **Freshness / TOCTOU:** proposals carry `based_on_graph_version`; high-tier actions require a fresh target-identity validation inside the lease, else `STALE_CONTEXT`.
- **Defense-in-depth:** Policy Kernel (application decision) + executor egress firewall (network enforcement) must agree; the firewall is the last line.
- Outputs: `ALLOW`, `DENY`, `APPROVAL_REQUIRED`, `WAIT_FOR_RESOURCE`, `STALE_CONTEXT`, `ENGAGEMENT_STOPPED`, `OPSEC_HOLD`.
- Every decision is written to a `decision_record` in the hash-chained ledger.

### 7.4 OPSEC service (deterministic stealth)
Owns signal extraction, suspicion scoring, the heat-state machine, hard tempo caps, mandatory cooldowns, jitter, egress shaping, and the hard stop at `BURNED`. A compromised/injected LLM must not be able to override "too hot, stop." See §16.

### 7.5 Executors
Run exactly one typed invocation, enforce timeout, capture output and artifacts, stop on cancellation, terminate after work (process-group kill), and cannot choose next work.

---

## 8. Engagement Contract

```yaml
engagement:
  id: eng-001
  client_id: client-001
  authorization:
    method: web_checklist_attestation      # no document upload; legal SOW is signed offline & private
    attested_by: designated-user-id
    attested_at: timestamp
    manifest_signature: platform-signed
  validity: { starts_at: ts, expires_at: ts }
  mode:
    knowledge: blind
    execution: covert                        # blue team NOT informed; White Cell only
    tier: recon_only | recon_validate | full_kill_chain
    pacing: short | long_low_and_slow        # configurable per engagement
  objective:
    question: "Can an external attacker reach the approved objective, and would it be detected?"
    success: [objective_specific_proof, independent_verification, proof_artifact]
  scope:
    root_domains: []          # scope-by-ownership (any subdomain of an authorized apex)
    exact_hosts: []
    exact_addresses: []       # treated cautiously (cloud IP reuse)
    cloud_tenants: []
    exclusions: []
    third_party_boundaries: []
    ownership_proof: dns_txt | hosted_file   # G3: infra built, enforcement DORMANT initially
  capability_families:
    passive_intelligence: enabled
    active_recon: enabled                     # read-only, safe-recon rules apply
    credential_analysis: enabled              # offline-first
    authentication_validation: approval_required
    controlled_evasion: enabled               # loose-on-form / strict-on-effect
    controlled_exploit: on_hold               # until platform proven stable
    post_exploit: approval_required
    persistence: prohibited
    destructive_action: prohibited
  api_keys:                                   # BYOK; precedence client → operator-default → free
    shodan: byok_or_operator_default
    censys: byok_or_operator_default
    dehashed: byok_or_operator_default        # breach data — PII/legal handling required
  budgets:
    total_requests: 500
    per_agent_requests: {}
    maximum_concurrency: 2
    maximum_duration_hours: 8                 # short profile; long profile spans days
    maximum_cost_usd: 5                        # hard financial circuit breaker
  stop_conditions:
    - white_cell_stop
    - service_instability
    - target_identity_uncertain
    - third_party_boundary
    - real_incident_collision
    - unexpected_sensitive_data
    - operator_heartbeat_lost                  # dead-man auto-halt
```

---

## 9. Agent Communication

No arbitrary agent-to-agent commands. Agents communicate through typed **publications, proposals, handoffs, evidence challenges, and lifecycle events**. Canonical flow:

```
agent publishes event → ledger persists → graph projector updates
→ Conductor evaluates work readiness → target agent receives work order
```

BlackBread does not depend on a superseded ADR for these contracts. The minimum envelopes are:

- `AgentEvent`: `event_id`, tenant/engagement, monotonic sequence, schema name/version, producer,
  correlation/causation IDs, occurred/recorded timestamps, payload, payload hash, previous-event hash,
  event hash, sensitivity label, and redaction references.
- `ActionProposal`: proposal ID, agent/role instance, capability ID/version, target reference, typed
  parameters, intended proof, preconditions, oracle, risk, cost, information gain, OPSEC noise,
  requested budget, identity tier, graph version, idempotency key, and expiry.
- `WorkOrder`: proposal reference, immutable policy decision reference, approval reference where needed,
  lease/lock IDs, exact rendered-parameter hash, capability digest, budgets, deadline, cancellation token,
  expected evidence, cleanup obligation, and target-egress policy reference.
- `CapabilityOutcome`: work-order/invocation references, terminal status, typed result, raw-artifact
  references, oracle result, target binding, OPSEC/health signals, resource/cost use, cleanup result, and
  interpretation state. A capability outcome is evidence, never a confirmed finding by itself.

Schemas are versioned and additive changes require compatibility tests. Unknown schema versions,
missing security fields, expired proposals, and mismatched rendered-parameter hashes fail closed.

---

## 10. Shared and Private Memory

- **Canonical event memory:** PostgreSQL append-only, **hash-chained** table (what happened).
- **Shared world model:** PostgreSQL node/edge projection (verified current state).
- **Agent-local working memory:** private hypotheses, rejected alternatives, plans, notes — *never* world truth.
- **Artifact memory:** HTTP transcripts, screenshots, HAR, tool JSON, certs, redacted samples, reports, cleanup evidence — content-addressed and hashed.
- **Secret memory:** raw passwords/tokens/cookies/session material/API keys — only in the credential vault and Session/Secret Broker; graph and events use opaque references.

The LLM is fed a **retrieval-augmented slice** of the verified graph per step, never the full history — this keeps behavior consistent across long low-and-slow engagements.

---

## 11. Agent 1 — Scout

**Mission:** discover and prioritize evidence-backed external primitives across the *full* authorized surface, minimizing target interaction and false association.

**Local goal:** maximize honest resolution of the authorized surface while minimizing footprint and false association.

**Surface breadth (must NOT be web-only):**
- Web/HTTP apps and APIs.
- **Edge / remote-access appliances** (VPN/SSL-VPN gateways, e.g., Fortinet/Citrix/Ivanti/Pulse classes) — the dominant real-APT external initial-access vector.
- Mail (SPF/DKIM/DMARC posture, mail servers), RDP, exposed databases, SSH, **cloud storage buckets**, DNS infrastructure, mobile-app backends, VoIP/IoT/OT.

**Evidence-driven discovery (fixes the "everything is 404" failure):**
- **Response calibration / oracle:** learn each host's true not-found and found fingerprints (status + length bucket + body similarity hash + DOM + title + `ETag`/`Last-Modified`/`Content-Type` + timing). A 200 that matches the soft-404 baseline is a negative.
- **Observe → derive → targeted probe**, not blind wordlist spray: parse HTML/JS, extract routes from JS bundles and source maps, use `robots`/`sitemap`/`.well-known`/headers/cookies for stack hints.
- **Stack-aware conventions:** fingerprint the stack, then generate stack-specific candidates (e.g., Next.js `/_next/data`, Laravel `.env`/`telescope`, Django `/admin`, Rails `/rails/info`), and **mutate from real observed endpoints** (`/api/v1/users` → `v2`, singular, `/export`).
- **Access-context module** (former Anchor cognition): activated for authenticated recon; resolves effective identity/role/tenant/privilege via broker-held sessions.

**Safe-recon rules (do-no-harm applies to recon too):** read-only GET-only discovery (never POST/PUT/DELETE in recon); never submit forms; never follow logout/delete/reset/state-changing links (heuristic detection); never enter credentials except in the controlled credential-validation workflow; respect health-throttle and no-touch flags; sandbox any payload test.

**Tools:** Subfinder/Amass (passive), dnsx/tlsx/httpx, Nmap/Naabu (authorized), gau/waybackurls/Katana, Playwright/Camoufox, Gitleaks/TruffleHog, selected Nuclei discovery templates — all behind typed adapters and the OPSEC egress. Proprietary: PassiveIntelMap, Asset Ownership Resolver, **Target Identity Guard** (§18), Surface Coverage Engine, Evidence-Guided Surface Ranker, plus **own DNS resolver/brute** and **own CT-log consumer** (build-fresh; reduce external dependency).

**Boundaries:** Scout cannot test credentials, exploit, mutate state, expand scope, perform unrestricted enumeration, or classify candidates as confirmed findings.

---

## 12. Agent 2 — Strike

**Mission:** determine whether Scout primitives are genuine, applicable, and operationally usable, using the minimum-risk verification method.

**Credential workflow (offline-first + abuse prevention):**
```
candidate → normalize → classify → dedup → provenance → target association
→ OFFLINE audit (hash crack / breach-corpus applicability / ranking)
→ Authentication Risk Governor → minimal ONLINE validation if needed → outcome
```
- **Offline** = credential *intelligence* (no target contact): breach-corpus applicability, hash cracking (John/Hashcat), provenance, dedup, ranking → a short high-probability list.
- **Online** = strictly bounded by the **Authentication Risk Governor** (deterministic, enforced with the Policy Kernel):
  - where online validation is explicitly approved, prefer a low-and-slow spray shape over brute-force, but never assume either is safe;
  - cap attempts = `min(operator_config, known safe margin below the verified lockout policy)` per account/app/window; if the lockout state or prior-failure count is unknown, default to zero online attempts unless an operator approves one exact attempt;
  - long inter-attempt delays; spread across accounts; hard-stop on any lockout/anomaly/heat signal;
  - **MFA present → stop** (finding: valid-but-MFA-protected; no MFA bombing).
  - These controls reduce rather than eliminate lockout risk. The platform must never claim that a numerical cap makes lockout impossible, and absence of lockout is reportable only when the lockout policy was safely established.

**Authorization / IDOR-BOLA workflow:** unauthenticated vs authenticated, principal A vs B, role A vs B, tenant A vs B, object ownership, bidirectional differential, independent object marker → finding or rejection (requires broker sessions).

**Web/service vulnerability validation:** safe, non-destructive existence checks (e.g., SSRF via out-of-band canary when that service is activated; blind SQLi via boolean/timing with a safe marker; auth bypass). Must distinguish **WAF-blocked** from **not-vulnerable** and record `ControlBlocked`/`ControlDetected`.

**Tools:** John, Hashcat, hash-id libs, Playwright/Camoufox, OWASP ZAP, mitmproxy, testssl.sh, selected Nuclei verification templates. Proprietary: Credential Intelligence Engine, **Authentication Risk Governor**, Secret Applicability Engine, Authorization Differential Engine, False-Positive Resolver.

**Boundaries:** no broad-spray, no unlimited mutation, no destructive action, no arbitrary exploit code, no persistence, no evasion after a denial.

---

## 13. Agent 3 — Exploit (ON HOLD until platform proven stable)

**Mission:** produce one controlled, approved, independently verifiable proof that a boundary can be crossed — **only after BlackBread is validated safe in the pre-production range (§27.4)**.

**Least-invasive-proof principle:** for many findings, *exposure + applicability + a safe oracle* is sufficient and preferred. For high-risk targets — especially **edge appliances** — prefer version/behavior/KEV-EPSS applicability proofs or non-destructive auth-bypass/info-leak over memory-corruption RCE, which frequently crashes production devices (a do-no-harm violation). Full RCE of production edge appliances is gated behind the capability lifecycle, qualification harness, blast-radius model, and explicit per-target approval (release R3+).

**Capability lifecycle:** `RESEARCH_DRAFT → STATIC_REVIEWED → FIXTURE_VERIFIED → NEGATIVE_CONTROL_VERIFIED → LAB_PROVEN → SAFETY_REVIEWED → CLIENT_ELIGIBLE → EXACT_TARGET_APPROVED → FIELD_OBSERVED → FIELD_PROVEN → REPEATABLE`.

**Runtime composition (permitted):** reviewed template + confirmed target context + typed parameters + declared effects + approved objective + predefined oracle + attempt limit + cleanup. **Not permitted:** an LLM generating an arbitrary exploit and mutating until it works.

**Tools/proprietary:** wrapped Nuclei/Metasploit/sqlmap modules and reviewed PoCs in isolated containers; Exploit Capability SDK, Runtime Capability Composer, Applicability Engine, Proof Oracle Engine, Effect & Blast-Radius Model, Capability Qualification Harness.

**Boundaries:** no novel uncontrolled payloads, no retry beyond budget, no hidden effects, no control-disabling, no persistence, no unrelated collection, no continuation after proof.

---

## 14. Agent 4 — Post-Exploit

**Mission:** determine whether one *separately approved* impact objective is reachable after access is established. Deferred beyond MVP.

**Activation prerequisites:** initial-access evidence sealed + valid access context + previous executor stopped + post-access objective selected + separate approval + new lease.

**Doctrine:** prove the approved objective with minimum additional action and complete cleanup. Exfiltration reachability is proved with **client-seeded canary data only**, never real customer data. Cloud pivots (e.g., SSRF→metadata→role→API) are read-only and objective-bound.

**Tools:** BloodHound as a candidate path generator (not truth), client-provided directory exports, cloud identity APIs, existing osquery/EDR live-response/SSH/WinRM where explicitly approved, scoped Kubernetes/app-admin/read-only DB clients. Proprietary: Objective Validator, Trust Boundary Graph, Native Capability Catalog, Segmentation Differential Engine, Post-Access Data Minimizer, Cleanup & Teardown Orchestrator.

**C2 (Sliver et al.):** not part of MVP, not a default, not autonomous, not required for an agentless product. Any future high-risk C2 workstream is isolated behind a separate SOW clause, exact target, dedicated approval, client observer, isolated infrastructure, and teardown.

**Boundaries (default):** no credential dumping, no persistence, no unrestricted lateral movement, no covert tunneling, no control-disabling, no customer-data collection, no durable access, no log modification.

---

## 15. Agent 5 — Report

**Mission:** independently determine what can be claimed and continuously reconstruct the evidence-backed attack chain. Report may disagree with and downgrade any other agent's claim.

**Severity & business impact:** CVSS v4.0 (or v3.1) technical base **+** a business-impact overlay mapped to the client's stated crown-jewels/objectives **+** exploitability enrichment (**EPSS**, **CISA KEV** — "do real attackers use this?") **+** exposure/reachability **+** evidence confidence. All components are shown transparently. Severity is **evidence-bounded**: rated for proven impact only; potential escalation is labeled separately (`proven_impact` vs `unproven_impact`). Report proposes the CVSS vector with justification; a deterministic calculator scores it; the operator can review.

**Client-runnable reproduction:** sanitized, platform-independent steps the client can run themselves (exact requests + oracle + screenshots/HAR + affected asset with target-identity binding + minimal evidence), redacted with a vault-retrieval path for their own values. The same repro drives retest after remediation.

**Finding maturity:** `OBSERVED → HYPOTHESIZED → CANDIDATE → SELF_VERIFIED → CROSS_VERIFIED → CLIENT_VERIFIED`.

**Coverage honesty states:** `ASSESSED_NO_FINDING`, `FINDING_CONFIRMED`, `BLOCKED`, `DETECTED`, `DECEPTION_ENCOUNTERED`, `INCONCLUSIVE`, `NOT_ASSESSED`, `NOT_APPLICABLE`, `CAPABILITY_UNAVAILABLE`.

**Report structure:** executive summary (business language) + technical findings (severity + repro + remediation) + coverage honesty + detection timeline (post-debrief) + attack-path narrative (verified nodes only). Deception that caught BlackBread is reported as a client defensive win.

**Tools/proprietary:** Jinja2/Markdown/HTML-PDF/Playwright/HAR/NetworkX; Evidence Resolution Engine, Finding Maturity Engine, ProofArtifact Builder, Attack Path Narrator, Coverage Honesty Engine, Defensive Outcome Correlator, Remediation & Retest Manager.

---

## 15b. Session/Secret Broker (service, former Anchor)

Deterministic trust-spine service (not an agent). Provides opaque session handles without exposing raw cookies/tokens to agents; resolves `session → principal → tenant → application → role → boundary`; enforces objective-bound sessions (one engagement, target, objective, window, capability set); provides authenticated-surface handoff to Scout; and verifies revocation (session invalidated, token expired/revoked, temporary state removed, no residual access). Secrets are per-engagement, ephemeral, and scoped.

---

## 16. OPSEC & Stealth Subsystem

**Core principle:** deterministic danger-stop, cognitive sneakiness.

**Suspicion signals (deterministic extraction per response):** WAF/CDN blocks and challenges (403/406/429, CAPTCHA/JS challenge, Cloudflare/Akamai fingerprints), redirects to verify/interstitial, `Retry-After`, TCP resets/timeouts after prior success, egress-only unreachability (likely IP-blocked); latency inflation (tarpit), 200-but-generic soft-blocks, A/B inconsistency, "request blocked / id" echoes, honeytoken hits; time-of-day and cumulative volume vs inferred thresholds; newly appearing security headers/WAF; White Cell out-of-band "blue team escalating."

**Heat state machine (EWMA with decay):** `COOL → WARM → HOT → BURNED`.
- **WARM:** slow down, more jitter, lower concurrency, drop noisy techniques.
- **HOT:** stop the current technique/path; switch approach (other technique / other asset / verified origin instead of CDN) or cool down.
- **BURNED:** **freeze all target-active work for the affected engagement and notify the operator/White Cell**. Passive analysis may continue, but no autonomous active flanking or cooldown-based resume is allowed. Resume requires an operator-authorized recovery decision, a fresh target-identity check, a new lease, and an explicitly different approved path. A genuine block is reported as a client defensive win.

**Jitter engine:** log-normal inter-request delays (human think-time), Poisson arrival for organic emulation, circadian shaping, burst-then-idle session model, per-host and global token buckets, AIMD backoff tied to signals, order shuffling, and parameter variation to avoid self-signature.

**De-signaturing:** OSS tools run behind a normalizing egress proxy (mitmproxy addons) that centrally enforces browser-like User-Agent, header order/casing, **TLS JA3** (utls/curl-impersonate), and HTTP/2 fingerprints, plus pacing. Custom payloads/markers replace tool defaults (loose-on-form/strict-on-effect). The goal is realistic emulation — remove the *lazy* signatures a competent attacker would remove; whatever still trips detection is reported as a client win.

**WAF/CDN bypass & origin discovery:** primary bypass is the **verified origin** (see §18); signature evasion uses the reviewed technique library, never arbitrary mutation.

---

## 17. Deception / Honeypot Detection Module

Not an agent — a shared analyzer feeding Scout and Strike, reinforced by the verification pipeline. Detects honeypots (Cowrie/Dionaea/Conpot/T-Pot/Honeyd), honeytokens (planted creds/keys, canary URLs, decoy docs), tarpits, and deceptive "fake-vulnerable" responses via combined heuristics: too-easy/too-good access, fingerprint inconsistency, known-emulator artifacts, environmental implausibility, tarpit timing, canary-token shape, interaction inconsistency, and bait-like naming.

On high suspicion: avoid active/exploit action by default, record `DeceptionEncountered`, do **not** blind-use planted credentials/keys (using a canarytoken tips off defenders and may alert a third party), and **report honestly** as a positive for the client's detection posture. Detection is heuristic and adversarial — probabilistic, cautious, never claimed as certain. Genuine "realness" of graph findings is guaranteed by the *pipeline* (Scout emits candidates only → Target Identity Guard → evidence independence/oracle → False-Positive Resolver → Report downgrade), not by one component.

---

## 18. Target Identity Guard (tiered)

Binds evidence to a specific identity (hostname, IP, certificate, application, tenant, timestamp) and classifies ownership (`AUTHORIZED`, `PROVISIONALLY_RELATED`, `THIRD_PARTY`, `EXCLUDED`, `UNKNOWN`) with confidence. Ground truth is the scope manifest; corroborating signals are DNS resolution/CNAME, TLS cert SAN/CN, RDAP/WHOIS/ASN ownership (also detects "this IP is a CDN, not an origin"), HTTP unique-marker echo, and reverse DNS.

**Origin verification (build in-house):** request the candidate origin IP with the target `Host` header and compare fingerprint (favicon hash + title + unique markers) to the CDN-fronted response; a match implies the origin, a shared-hosting default does not — do not touch.

**Confidence tiers (architecture fixed; enforcement starts lenient, tightens later):**
- **T0** passive-only — allowed at low confidence, no active touch.
- **T1** active read-only on an in-scope hostname — scope + DNS + cert match.
- **T2** origin-direct / CDN bypass — cert match + unique-marker echo + ASN-not-CDN + Host-header behavior.
- **T3** exploit/mutating — T2 + fresh re-validation inside the lease (TOCTOU guard).

**MVP posture:** T0/T1 enforced automatically; T2/T3 require operator confirmation until maturity/volume justify auto-enforcement.

---

## 19. Browser Service

Do not build a browser engine. Two-tier execution behind a swappable adapter:
- **Fast path:** TLS-impersonation HTTP client (utls / curl-impersonate) for the bulk of HTTP/API work — authentic JA3/HTTP2, cheap, defeats many bot verdicts without a browser.
- **Heavy path:** **Camoufox** (hardened Firefox) driven by Playwright for real JS/SPA/challenge/DOM — used sparingly (detection risk and RAM concentrate here; concurrency capped at 1–2 on the 12 GB VM).

"AI-native" browsers are cognition tools, not stealth tools; the LLM decides and drives Camoufox/utls via typed actions. Responsibilities: isolated context per engagement and per identity, scope-aware navigation, redirect enforcement, client-mediated login, session custody, DOM/API observation, screenshot/HAR capture, redaction, and profile destruction.

---

## 20. Capability Gateway

Every tool — open-source, commercial, or proprietary — runs behind one typed contract declaring eligible agents, risk class, input/output schemas, limits, and evidence requirements (raw artifact + target binding). **Customization order:** adapter → official plugin/extension/template → maintained fork only when commercially justified. Prefer library/JSON output over CLI scraping; customize at extension points (Nuclei templates, mitmproxy addons, sqlmap tamper scripts); build-fresh the small high-value components (resilience layer, resolver/brute, CT consumer). Do not fork a tool merely to call it proprietary.

### 20.1 Canonical capability and tool registry

`config/capability-registry.json` is the machine-readable source of truth for capability ownership.
Names in agent descriptions are architectural candidates, not permission to install or execute a tool.
The runtime must default-deny anything absent from the registry and, from M2 onward, load the same
registry used by CI. Each entry must declare a stable capability ID, owning agent, adapter, pinned tool
or image identity, lifecycle state, risk class, Target Identity Guard tier, approval mode, network path,
typed input/output schema references, budgets, evidence/oracle requirements, cleanup behavior, and
prohibited effects.

No agent receives shell access, a generic HTTP client, arbitrary command arguments, raw template
selection, or a tool binary directly. The adapter builds the final invocation from validated typed
fields. Redirects, callbacks, proxy destinations, file inputs, and body-embedded destinations are
re-extracted and scope-checked after rendering. Tool updates and template changes are capability
changes: they require a review, digest pin, fixture and negative-control tests, and lifecycle promotion.
Discovery of a locally installed binary never grants eligibility.

The initial ownership matrix is binding:

| Capability family | Owner | Candidate engines | Maximum default posture | Required restriction |
|---|---|---|---|---|
| Passive asset intelligence | Scout | own CT/DNS consumer, Subfinder, Amass, Wayback/CDX, Common Crawl, OTX, URLScan | T0 passive | source provenance, deadlines, cache, no target contact |
| DNS/TLS/HTTP observation | Scout | dnsx, tlsx, httpx, curl-impersonate | T1 active read-only | exact destinations, GET/HEAD only for HTTP, redirect re-check |
| Network-service observation | Scout | Naabu, Nmap safe profiles | T1 active read-only | approved ports/rates; no NSE, brute, UDP, or version script unless separately allowlisted |
| Route and browser observation | Scout | gau, waybackurls, Katana, Playwright/Camoufox | T1 active read-only | no forms, downloads with side effects, state-changing links, or credential entry |
| Public-artifact secret detection | Scout | Gitleaks, TruffleHog | offline artifact analysis | only already authorized/publicly retrieved artifacts; findings store redacted evidence |
| Discovery signatures | Scout | Nuclei discovery templates | T1 active read-only | reviewed template-ID allowlist; no fuzzing, auth, headless, file, code, or destructive tags |
| Credential intelligence | Strike | John, Hashcat, hash-identification libraries | offline only by default | approved corpus, isolated worker, secret handles only, no target contact |
| Authentication validation | Strike | BlackBread typed auth adapter, brokered browser | T2 operator approval | exact account/app/window, verified lockout margin, MFA/lockout hard stop |
| Authorization differential | Strike | brokered browser/API differential adapter | T2 operator approval | two approved principals, read-only object markers, no enumeration |
| Service/vulnerability verification | Strike | testssl.sh, mitmproxy, reviewed Nuclei/ZAP checks | T1 or T2 per check | one declared oracle; active scanner and unrestricted spider disabled |
| Controlled proof | Exploit | reviewed Nuclei/Metasploit/sqlmap modules and reviewed PoCs | T3 exact-target approval | lifecycle `ON_HOLD` until R3; isolated worker, attempt cap, effect model, cleanup |
| Objective-bound post-access read | Post-Exploit | approved native APIs/clients and client-provided exports | T3 separate approval | client-seeded canaries, data minimization, no persistence or credential dumping |
| Evidence and report build | Report | Jinja2, NetworkX, Markdown/HTML-PDF, Playwright render | offline/control plane | read-only evidence handles; independent verification; deterministic severity calculation |

Shared services such as the Policy Kernel, OPSEC gateway, Session/Secret Broker, evidence store, and
LLM provider are not agent capabilities and cannot be invoked as a way around the Conductor. The
Report agent may request a re-verification work order, but may not directly operate a Scout, Strike, or
Exploit tool.

### 20.2 Capability admission gate

A capability cannot move to `CLIENT_ELIGIBLE` until all of the following are present: pinned supply-chain
identity, typed schemas, eligible-agent allowlist, risk/tier/approval classification, deterministic scope
tests including nested destinations and redirects, timeout/cancellation/process-group cleanup, resource
and cost budgets, output redaction, evidence oracle, fixture and negative-control tests, OPSEC signal
mapping, ARM64 qualification, and an owner. A missing field or failing test keeps the capability denied.
`ON_HOLD` and `PLANNED` entries are visible design inventory, never executable runtime states.

**Passive-source resilience layer:** a `PassiveSource` interface with multi-source redundancy, a per-engagement PostgreSQL cache, per-source retry/backoff/circuit-breaker, async per-source deadlines (never stall the run), and source-health metrics. Free-source floor: Wayback Machine + Wayback CDX, Common Crawl, AlienVault OTX, VirusTotal (off the critical path), URLScan, and crt.sh via its public PostgreSQL. Paid sources (Shodan/Censys/Dehashed) are BYOK with operator-default fallback.

---

## 21. Attack Graph

```
hash-chained event ledger → PostgreSQL projection → immutable NetworkX snapshot → path analysis
```

PostgreSQL is canonical and durable; **NetworkX is an ephemeral, rebuildable analysis view**
(restart-safe by design — rebuild from the projection or by replaying the ledger; snapshot periodically
for fast startup). Layers are Observed, Belief, Action, Access, and Objective.

Canonical node families are `ScopeRoot`, `Host`, `Address`, `Service`, `Certificate`, `Application`,
`Endpoint`, `CloudResource`, `Identity`, `Tenant`, `Artifact`, `SecretRef`, `VulnerabilityCandidate`,
`Control`, `AccessContext`, `Finding`, and `Objective`. Canonical edge families are `RESOLVES_TO`,
`PRESENTS`, `EXPOSES`, `BELONGS_TO`, `OBSERVED_AT`, `INDICATES`, `APPLICABLE_TO`, `VERIFIED_BY`,
`GRANTS`, `TRUSTS`, `REACHES`, `BLOCKED_BY`, `SATISFIES`, `DERIVED_FROM`, and `SUPERSEDES`.

Every node/edge carries tenant and engagement, target-identity binding, first/last observed,
valid-from/until, evidence references, confidence, producer, graph version, freshness, verification
state, and supersession. Belief edges cannot satisfy an objective or appear in a verified attack path;
each promoted edge requires its declared oracle and evidence. Cross-tenant edges are prohibited. A
graph database is deferred until measured PostgreSQL path-query limits justify it.

---

## 22. Finding Verification

```
target identity → observation integrity → applicability → independent evidence → objective oracle → human-legible ProofArtifact
```

Two tools reading the same header are not independent evidence. Independent families include HTTP behavior, static artifact, authenticated-client observation, server-side audit, differential account/object behavior, and vendor/version metadata.

```yaml
payable_finding:
  target_binding: confirmed
  status: cross_verified
  independent_evidence_families: 2
  proof_artifact: present
  proven_impact: explicit
  unproven_impact: explicit
  severity: { cvss: vector+score, business_impact: mapped, epss: n, kev: bool }
  cleanup_state: verified_or_not_required
  coverage_limitations: present
```

---

## 23. Vulnerability Intelligence

Ingest NVD/CVE feeds, vendor advisories, exploit-db, **EPSS**, and **CISA KEV** into a local cache (no live external calls at query time). Map to fingerprinted product + version and emit `VulnerabilityCandidate` with **probabilistic** applicability and KEV/EPSS priority. **Version strings lie and patches are back-ported** — "vulnerable version" is not "vulnerable"; applicability must be confirmed behaviorally where safe, not by version string alone. This subsystem powers the edge-appliance and service lanes.

---

## 24. Agent Cognition

Each agent runs an OODA loop:
1. **Observe** a relevant slice of the verified world model (not raw LLM memory).
2. **Orient** — the LLM planner generates typed candidate actions, each labelled with `{proves, precondition, info_gain, risk, cost, opsec_noise}`.
3. **Critic** — an LLM/role and/or rules pass challenges evidence, duplication, scope, oracle, and stealthier alternatives.
4. **Rank** — a deterministic formula over LLM estimates.
5. **Decide** — emit a typed proposal; Conductor + Policy Kernel + OPSEC gate it. The LLM never executes.
6. **Act** — an executor runs the typed capability via the egress gateway.
7. **Interpret** — the LLM proposes; deterministic oracle + evidence rules confirm/reject; Report can downgrade.
8. **Update** the graph and loop.

**Anti-loop:** novelty/dedup gate (hash of capability + target + params); per-path progress requirement (prune to `INCONCLUSIVE` after N steps without info gain); a ranked frontier with a global stop when empty; hierarchical budgets (path/agent/engagement).

**LLM: multi-provider.** A provider abstraction with structured/schema-constrained output, streaming, tool-calling, and token accounting. One OpenAI-compatible adapter covers OpenRouter, DeepSeek, Qwen/DashScope, Together/Groq, and local vLLM/Ollama; native adapters for Anthropic/Google. A **deterministic router** = f(role, task type, data sensitivity, budget, provider health, refusal propensity). MVP: OpenRouter + the OpenAI-compatible adapter; a mixed router with local self-hosting deferred to a separate box.

**Refusal handling (not jailbreaks):** genuine authorization context in the system prompt; task decomposition so the LLM does narrow analytical sub-tasks (extract/rank/classify over structured data), never "hack X"; structured/tool-calling I/O; route security-flavored reasoning to permissive/open models; keep weaponization out of the LLM (reviewed capability library). Respect provider ToS.

**Prompt-injection defense:** target content is untrusted data, never instructions; a low-privilege reader extracts it into structured facts and the planner reasons only over those facts; the typed-output backstop means even a fully injected agent can only emit a proposal that the Policy Kernel + OPSEC + scope still gate; provenance tagging; and an injection test suite as an acceptance gate.

---

## 25. Try-Harder Semantics

Continue exploring authorized, evidence-supported alternate paths while the frontier contains useful work and hard budgets remain. Per-agent: Scout finds alternate surfaces; Strike finds safer verification or another primitive; Exploit checks another reviewed applicable capability; Post-Exploit selects another approved proof method (not another objective); Report records exhausted and unresolved branches honestly. Global stop when ready proposals, active work, waiting approvals, waiting operator actions, retriable source failures, and useful authorized hypotheses are all zero.

---

## 26. Agentless Execution & Cleanup

External: DNS, TLS, HTTP, browser, public sources, approved protocols, client-mediated sessions. Authenticated: application APIs, browser session, short-lived cloud token, client-issued session, approved admin interface. Post-access: prefer existing client channels. Cleanup invariant:

```
objective completed → sessions revoked → temporary state removed
→ ephemeral worker destroyed → target state reconciled → cleanup evidence recorded
```

Orphaned-session recovery: on restart, sessions and in-flight state are reconstructed from the ledger and reconciled or revoked.

---

## 27. Infrastructure

### 27.1 MVP — single Oracle Cloud VM (12 GB RAM / 4 OCPU, ARM Ampere), Docker Compose
Components: API/Conductor (FastAPI + SSE); PostgreSQL (canonical ledger + projections + state + artifact metadata); agent workers (Scout/Strike/Report, stateless); OPSEC/egress gateway; Browser Service (Camoufox heavy path, capped 1–2; utls fast path); capability workers (isolated containers, no Docker socket, egress only via gateway); Session/Secret Broker + vault; artifact store (encrypted local + off-box encrypted backup); scheduler (due-time queue for low-and-slow); LLM provider layer.

**Resource reality:** cap browser concurrency; **do not run a local LLM on this box** (it would starve the stack) — MVP reasoning is cloud via OpenRouter; local self-hosting moves to a separate box later. Ensure all images are arm64 (verify Camoufox and each OSS tool).

### 27.2 Network separation (critical)
Target egress (scope-locked, stealth-shaped, via OPSEC gateway) is strictly separate from control-plane egress (LLM APIs, OSINT sources, package installs).

### 27.3 State model
Engagement is a durable PostgreSQL entity; everything is resumable via ledger replay. Workers are stateless/ephemeral; low-and-slow "sleeping" is the scheduler deferring work orders by not-before timestamps. Pacing profiles: short vs long. Backup off-box (Oracle VM may be suspended). Synced clock. On resume, re-validate target identity (TOCTOU); heat decays during sleep.

### 27.4 Pre-production safety range
A lab with vulnerable, fragile, and honeypot targets to prove do-no-harm, scope adherence, BURNED handling, and stealth **before** any covert real-client run. The Exploit phase stays on hold until this range validates stability.

### 27.5 Later phases
Split control-plane/worker VMs; object storage; Redis; OpenTelemetry/Prometheus/Grafana; managed PostgreSQL; per-tenant keys; DR; optional Go/Rust executor and graph-DB projection. The PostgreSQL event ledger remains canonical.

---

## 28. Data Model

`clients, engagements, engagement_policies, objectives, agent_instances, agent_events (hash-chained), agent_working_memory, action_proposals, work_items, execution_leases, resource_locks, approvals, budgets, graph_nodes, graph_edges, hypotheses, findings, artifacts, tool_invocations, capability_versions, access_contexts, decision_records, coverage_records, cleanup_records, learning_records, attestations, api_keys (vault refs), opsec_events, vuln_intel, deception_events`.

---

## 29. Platform Security (including self-security)

**Threats:** prompt injection from target content, malicious scanner output, malicious public repos, compromised tool containers, dependency compromise, secret leakage, tenant leakage, arbitrary command generation, path traversal, SSRF, target substitution, artifact tampering, worker takeover, **and BlackBread itself as a high-value target** (it holds multi-client secrets and is designed to evade detection).

**Controls:** target content treated as untrusted; strict schemas; no LLM-generated shell; no raw secrets in prompts; container isolation; binary/version allowlists; tool image digest pinning; dependency scanning; target allowlist inside the executor + L3/L4 egress firewall; per-tenant access control and isolation (row-level security or separate schemas; per-client vault); artifact encryption; output-size limits; append-only hash-chained audit; redaction before LLM processing; short-lived per-engagement scoped secrets and rotation; executor process-group kill; no Docker socket in workers; dual-control for sensitive operations and insider/rogue-operator auditing; dead-man/heartbeat auto-halt; hard financial circuit breaker at the LLM/OSINT call layer.

**Security tooling:** Ruff, mypy/Pyright, pytest, Hypothesis, Bandit, Semgrep, Trivy, Syft/Grype, Gitleaks, pip-audit, pre-commit, dependency-update automation.

---

## 30. Evidence Integrity

Hash-chained append-only ledger; SHA-256 artifact hashing with content-addressed storage; decision provenance (model + version + prompt hash + inputs + output per LLM decision); chain of custody per evidence (producer, synced timestamp, target-identity binding, graph version, chain link); time integrity (NTP + monotonic sequence numbers); redaction-with-integrity (encrypted+hashed original + redacted view + recorded transformation); a verify routine before sealing a report. Signing (platform key), RFC-3161 timestamping, and WORM/object-lock are added later. MVP subset: hash-chained ledger + artifact hashing + content-addressed store + decision provenance + synced clock + off-box encrypted backup + verify routine.

---

## 31. Client Portal & Authorization

- **Access:** designated client users only (RBAC, MFA); no open registration.
- **Authorization:** a web setup wizard (scope inputs with ownership helpers, objective, budgets, pacing, window, stop conditions, deconfliction contacts) plus an in-app **attestation** (authorized-to-consent, scope confirmation, rules-of-engagement acknowledgment, click-sign) that generates a machine-readable, platform-signed engagement manifest. **No document upload** — the offline legal SOW is signed privately between operator and client and is not uploaded. The attestation (who, when, exact scope, mode) is recorded immutably in the hash-chained ledger, making the checklist non-repudiable proof of authorization. The Policy Kernel refuses to act without a valid, unexpired, attested manifest.
- **Engagement modes (3 tiers):** Recon-only (passive + active-read-only Scout, restricted offline/T1 Strike verification, and Report; MVP/first sellable tier), Recon+Validate (adds approved T2 Strike validation), Full kill-chain (adds Exploit + Post-Exploit, separately approval-gated). Mode is a gating field that enables exact registry capabilities and agent profiles, not merely agent names.
- **BYOK API keys:** clients may supply their own Shodan/Censys/Dehashed/etc. keys (encrypted, per-engagement, opaque refs, never logged); precedence is client → operator-default → free-source fallback; default is operator-set. Dehashed (breach data) is handled under PII/legal rules.
- **Ownership proof:** DNS TXT / hosted-file automation may remain dormant for R1, but a documented manual ownership review with evidence, reviewer identity, timestamp, and expiry is mandatory before active target contact. Unknown, third-party, CDN/provider, and shared-SaaS infrastructure fails closed.
- **White Cell / deconfliction:** sealed attested authorization, 24/7 contact, an "is this activity yours?" ledger query, a dual-mode kill switch (freeze/forensic-hold vs graceful-stop), immediate critical-finding disclosure, real pre-existing-breach handling, real-incident-collision pause, and a law-enforcement runbook.

---

## 32. Observability

Platform metrics (queue depth, worker heartbeat, task duration, tool failure rate, lease expiration, cleanup failure, cost, request count); agent metrics (proposals created/allowed/denied, conclusive-outcome rate, information gain, duplicate work, false-positive rate, actions per finding); mission metrics (objective progress, coverage, verified/blocked paths, detection timeline, remaining frontier, budget). **Operator async alerting** (BURNED, critical finding, anomaly, budget, target instability) for unattended low-and-slow covert runs.

---

## 33. Learning System

Learn capability reliability, target-context applicability, false-positive patterns, evidence-family value, information gain, request cost, blocked/detected outcomes, path priors, cleanup reliability, and honeypot fingerprints. Never retain raw credentials/sessions, client names, IPs/hostnames, customer data, reusable target-specific payloads, or sensitive response content. Pipeline: engagement event → tenant-isolated outcome → sanitization → aggregation → lesson candidate → human review → replay evaluation → shadow recommendation → controlled promotion. Record data immediately; build adaptive ranking only after enough field outcomes exist.

---

## 34. Moat

Evidence-backed attack-path intelligence learned from conclusive real-world outcomes, plus: the Target Identity & Ownership Graph, Credential Intelligence, the Authorization Differential Engine, the Runtime Capability Composer, Capability Qualification and Field Maturity, the Evidence Resolution Engine, attack-path composition, the Defensive Outcome Graph, agentless session custody, the covert OPSEC/stealth stack (heat, jitter, de-signaturing, origin discovery, honeypot awareness), and the learning flywheel. **Not** a moat: the agent names, a particular LLM, NetworkX, individual tool integrations, template counts, raw payload collection, a visual monologue, or tool wrapping alone.

---

## 35. Build Plan

**Milestones (MVP path to first finding):**
- **M0 — Skeleton:** Python 3.12, Docker Compose (arm64), PostgreSQL, FastAPI, Pydantic, SQLAlchemy/Alembic, pytest, ruff/mypy, encrypted artifacts. Exit: compose up + migrations + healthcheck.
- **M1 — Trust spine (R0):** data model, hash-chained ledger + replay + graph projection + NetworkX rebuild, Conductor, Policy Kernel v1, dual kill-switch. Exit: no action without a lease; out-of-scope denied; replayable.
- **M2 — Capability Gateway + OPSEC/egress + passive capabilities:** typed contract, isolated executor, OPSEC gateway (scope-lock + TLS/JA3 shaping + jitter + suspicion/heat), resilience layer, passive sources + own resolver. Exit: passive recon via gateway, scope-locked, cached, outage-resilient, heat observable.
- **M3 — Scout + Target Identity Guard T0/T1 + graph:** cognition loop, evidence-driven discovery + calibration oracle + anti-loop; full-surface discovery (incl. edge/service, safe-recon). Exit: honest calibrated surface resolution + coverage honesty.
- **M4 — Strike + first-lane validation:** cognition loop, exposed-artifact/secret applicability (offline-first), evidence independence, false-positive resolver. Exit: candidate → validated primitive with ≥1–2 independent evidence families.
- **M5 — Report + ProofArtifact + first finding:** independent verification, evidence resolution, finding maturity, severity model, ProofArtifact, live report. Exit = R1 oracle (below).
- **M6 — State/low-and-slow/backup:** durable engagement, ledger-replay resume, due-time scheduler, off-box encrypted backup, short/long profiles.

**Releases:** R0 Trust Spine → R1 First Payable Finding (Recon-only tier) → R2 Full Broker + authenticated recon → **R3 Controlled Exploit (only after pre-production safety range validation)** → R4 Post-Exploit → R5 Learning & Scale.

The Recon-only product uses Scout plus a **restricted Strike verification profile** and Report. Restricted
Strike may perform only offline or T1 read-only confirmation needed to reject false positives; online
authentication, authorization differential testing, exploit, and mutation remain outside this tier.

**R1 entry gate (before any real target):** R0 evidence is sealed; mandatory CI checks are required by
branch protection; the capability registry is runtime-enforced for every target action; no inherited
P0/P1 or safety blocker is open; legal counsel has approved the operating SOW/attestation, UU ITE/UU
PDP handling, cross-border processor use, breach-data policy, retention/deletion schedule, and incident
procedure; manual ownership verification is recorded in the ledger while automated proof remains
dormant; shared-SaaS, third-party, and unknown ownership are fail-closed; White Cell/deconfliction and
kill/dead-man drills have passed; backup restore and evidence deletion have been tested.

**R1 exit oracle (first finding lane = phase exit):** on one authorized real target, the full Scout →
restricted Strike → Report chain yields a cross-verified finding (≥2 independent evidence families)
with a ProofArtifact, severity, and coverage honesty, with zero scope/availability/lockout/data-handling
incident, no unresolved BURNED state, and client-accepted interpretation. Any failed gate downgrades the
finding and the phase is not exited.

Every milestone exit must publish a versioned conformance record containing requirement IDs, commit
SHA, passing CI run, negative-test evidence, open-gap list, operator approver, and timestamp. An empty
or missing record means the milestone is not exited.

---

## 36. Decision Acceptance and Implementation Conformance

This ADR is accepted because the architectural choices and safety boundaries are resolved. Acceptance
does not certify implementation. A build is conformant only when automated evidence proves: five agents
have non-overlapping local goals; the Conductor has no strategic LLM planner; each agent has typed I/O;
proposals cannot execute directly; the Policy Kernel controls the exact rendered invocation and every
destination; raw secrets cannot enter events, graph, logs, prompts, or ordinary artifacts; target
identity is verified at the required tier; registry-denied tools cannot execute; tool output cannot
directly create confirmed findings; Report can downgrade claims; Exploit cannot auto-start Post-Exploit;
Post-Exploit requires a separate approval and lease; cleanup is a mandatory lifecycle state; agentless
execution is tested; prompt injection cannot alter authority; the OPSEC hard stop cannot be overridden;
and milestone-specific release evidence exists.

R3 additionally requires the pre-production safety range to validate do-no-harm, scope adherence,
blast-radius assumptions, cancellation, cleanup, and negative controls. No provider free tier, optional
bot, or third-party service may be a release dependency without a tested degraded/fail-closed path.

---

## 37. Decisions Resolved

Five agents, no central brain. Anchor dissolved → Session/Secret Broker service + Scout access-context module. Conductor = deterministic orchestration; Policy Kernel = deterministic, fail-closed, deep-validating; OPSEC = deterministic stealth. No direct agent-to-agent commands. Covert posture with White Cell and web attestation (no document upload). Controlled evasion is first-class (loose-on-form/strict-on-effect). `BURNED` freezes target-active work until an operator-authorized recovery. Single controlled Oracle egress (no IP rotation yet). Multi-provider LLM via OpenRouter first, mixed router, cloud reasoning for MVP. Attack graph canonical in PostgreSQL; NetworkX rebuildable. Full-surface discovery (incl. edge/service) is in scope; edge RCE exploitation is gated to R3+. Exploit phase on hold until the safety range validates stability. BYOK API keys with operator default and free fallback. Automated ownership proof and OOB/canary infrastructure may be dormant, but manual evidence-backed ownership verification and fail-closed third-party handling are required for R1. C2/Sliver excluded. Go/Rust and graph DB deferred.

---

## 38. Open Questions / Future

Legal/compliance for Indonesia is not deferred architecture work: the R1 entry gate requires approved
controls for UU ITE authorization evidence, UU PDP No. 27/2022 data handling, cross-border processors,
breach data, retention/deletion, and incident response. Counsel decides the operational policy; agents
cannot waive it.

- Continuous/periodic re-assessment mode (find exposure before an attacker appears, continuously).
- Compliance-aligned reporting (ISO 27001 / SOC 2 / PCI) and localized (Bahasa Indonesia) reports.
- Responsible-disclosure automation for third-party/vendor vulnerabilities; the manual reviewed procedure is required for R1.
- Richer shared-SaaS handling; until then, provider infrastructure is deny-by-default and only the client's exact tenant/configuration may be observed when explicitly authorized.
- Dynamic scope evaluation for wildcards and rotating cloud IPs (scope-by-ownership vs scope-by-IP); immediate propagation when a client removes an asset mid-engagement.
- Egress source rotation (deferred with single-egress MVP).
- Local model self-hosting on a dedicated box for sensitive engagements.
- Composition-risk checks in the Policy Kernel (individually-safe capabilities that are dangerous combined).

---

## 39. APT References (summary)

| Group | Adapted (discipline) | Not adapted (excluded harm) |
|-------|----------------------|-----------------------------|
| **APT41** | initial-access breadth, multiple entry hypotheses, reusable exposed primitives, rapid applicability | supply-chain compromise, indiscriminate exploitation, malware, infra abuse |
| **APT29** | identity/trust graph, credential provenance, patience, low-and-slow, alternate paths, access/post-access separation | token theft for durable access, covert persistence, concealed long-term access |
| **Lazarus** | chain composition with a per-edge oracle | financial theft, destruction, malware chains, bulk/covert exfiltration |
| **Volt Typhoon** | environment awareness, native read-only capabilities, minimal tooling, stealth, segmentation verification | persistence, credential extraction for keeps, log manipulation/anti-forensics, defense disabling |

---

## 40. Final Decision Text

BlackBread will be an agentless, threat-informed, external red-team / adversary-emulation platform composed of five autonomous domain agents — Scout, Strike, Exploit, Post-Exploit, and Report — each owning an independent local goal, planner, critic, working memory, capability portfolio, and stop conditions. There is no central Mission Brain. A deterministic Conductor, Policy Kernel, and OPSEC service control the engagement lifecycle, scope, authorization, budgets, resource locks, execution leases, stealth pacing, cancellation, and cleanup without selecting offensive strategy. Session and secret custody is a deterministic service, not an agent.

The platform operates covertly, emulating APT tradecraft (patience, stealth, identity/trust reasoning, chain composition, environment awareness) while remaining strictly authorized and non-destructive. Controlled evasion is a first-class, SOW-authorized capability that is loose on form and strict on effect. The target model is agentless with no permanent implant; sessions and post-access actions are short-lived, objective-bound, separately approved where required, and revoked after use.

Commodity tools are wrapped behind typed adapters and a single stealth-shaping egress gateway; proprietary development is concentrated on target identity, credential intelligence, authorization differential testing, evidence resolution, runtime capability composition, capability qualification, attack-path reasoning, session custody, OPSEC/stealth, deception awareness, defensive-outcome correlation, and sanitized field learning. The Exploit phase is held until a pre-production safety range validates do-no-harm and scope adherence.

The initial commercial exit is one cross-verified, evidence-backed payable finding on an authorized real target, delivered as the Recon-only product tier. Distributed brokers, autonomous specialist swarms, graph databases, Go execution workers, C2 frameworks, source-IP rotation, and adaptive learning are deferred until field evidence demonstrates a need.
