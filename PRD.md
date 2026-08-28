# BlackBread — Product Requirements Document (PRD)

- **Product:** BlackBread
- **Category:** Autonomous, threat-informed, external red-team / adversary-emulation platform
- **Positioning:** An external red-team exploitation service that *works like an APT operator* — covert, patient, objective-driven, evidence-backed — while remaining strictly authorized, non-destructive, and agentless.
- **Companion documents:** `ADR-FINAL-002.md` (architecture), `.devin/rules/blackbread.md` (engineering guardrails), `.devin/skills/build-blackbread-agent/SKILL.md` (build guidance).
- **Status:** Accepted product baseline for M0–R1; implementation status is tracked by tests and release evidence, not this document.

---

## 0. Requirement Authority and Status

`ADR-FINAL-002.md` governs architecture and safety. This PRD defines product behavior and measurable
release outcomes. Rules and skills may prescribe implementation technique but may not weaken either.
The machine-readable capability registry controls which tools an agent may propose; runtime policy
controls whether an exact invocation may execute.

Requirements use stable IDs and one of `DECIDED`, `IMPLEMENTED`, `VERIFIED`, or `RELEASED`. Status is
never inferred from prose. `VERIFIED` requires automated positive and negative tests; `RELEASED`
requires a milestone conformance record. Any missing P0/P1, authorization, scope, tenant-isolation,
evidence-integrity, OPSEC-stop, cleanup, or legal-entry requirement blocks the relevant release.

No release-blocking item may be hidden as `TODO`, `TBD`, dormant functionality, skipped/non-blocking
CI, or an undocumented waiver. Deferral requires an accepted ADR amendment, named owner, target
release, compensating control, verification plan, and expiry.

---

## 1. Problem & Opportunity

Organizations buy penetration tests that are noisy, announced, checklist-driven, and stop at "here are your vulnerabilities." They do **not** learn the two things that matter against real attackers:

1. *Can a capable external adversary actually reach something that hurts us?*
2. *Would we notice them?*

Scanners produce false positives; pentests are point-in-time and loud; BAS tools test pre-canned scenarios inside an already-instrumented environment. None of them behave like the APT groups that actually breach these organizations.

**BlackBread's opportunity:** deliver an autonomous platform that emulates APT tradecraft against a client's real external surface — covertly, with proof, and without harming production — so clients find and fix exploitable exposure *before* a real attacker does.

---

## 2. Vision

> A patient, stealthy, always-improving external operator that behaves like the adversaries clients fear, proves what it finds, tells the truth about what it could not assess, and never breaks anything.

---

## 3. Goals & Non-Goals

### 3.1 Goals (MVP)
- Deliver one **cross-verified, evidence-backed payable finding** on an authorized real target (the Recon-only tier).
- Operate **covertly** (blue team not informed) without causing outages, lockouts, or data loss.
- Produce findings a client can **independently reproduce** and act on, with defensible severity.
- Be **honest about coverage** — never imply "secure" from "nothing found."
- Reduce dependence on flaky/paid external services so recon still works with free sources.

### 3.2 Non-Goals (explicit, for MVP and by design)
- No malware, real persistence, covert C2, destructive actions, or anti-forensics.
- No human-vector attacks (phishing/social engineering) — deferred behind a separate consent/SOW framework.
- No exploit development against clients; no arbitrary LLM-generated payloads.
- No memory-corruption RCE of production edge appliances until the safety range validates stability (R3+).
- No source-IP rotation in MVP (single controlled egress).
- No on-box local LLM in MVP (resource-constrained VM).

---

## 4. Users & Access

- **Operator** — runs BlackBread, reviews approvals, handles BURNED/critical situations.
- **Sponsor** — the client's authority who attests to authorization and holds deconfliction/kill power.
- **White Cell** — the small designated client group aware of the engagement.

Access is **designated-only** (RBAC + MFA); there is **no open registration**. The client's blue team is deliberately **not** informed (covert red team).

---

## 5. Product Tiers (engagement modes)

| Tier | Scope | Agents/phases | Approval | Status |
|------|-------|---------------|----------|--------|
| **Recon-only** | Passive + active-read-only discovery and restricted offline/T1 candidate verification | Scout + restricted Strike + Report | Active recon; no online auth | **MVP / first sellable** |
| **Recon + Validate** | Adds approved T2 non-destructive primitive confirmation | Full Strike profile | Per-validation approval | Post-MVP |
| **Full kill-chain** | Adds controlled boundary proof + approved impact | + Exploit + Post-Exploit | Approval-gated | Gated (R3+) |

Tier is selected in the client portal and gates capability families and which agents run.

---

## 6. Functional Requirements

### 6.1 Engagement setup & authorization
- `ENG-001 [DECIDED]` Web setup wizard: scope (root domains, hosts, IPs, cloud tenants, exclusions, third-party boundaries), objective, tier, pacing profile (short vs long low-and-slow), budgets, window, stop conditions, deconfliction contacts.
- `ENG-002 [DECIDED]` In-app **attestation** (authorized-to-consent, scope confirmation, rules-of-engagement, click-sign) → machine-readable, platform-signed manifest. **No document upload**; the legal SOW is signed offline and private.
- `ENG-003 [DECIDED]` Attestation (who/when/scope/mode) recorded immutably in the hash-chained ledger.
- `ENG-004 [DECIDED]` **Ownership-proof challenge** (DNS TXT / hosted file) may be dormant initially, but evidence-backed manual ownership verification with reviewer, timestamp, and expiry is mandatory before active contact. Unknown/shared/third-party infrastructure fails closed.
- `ENG-005 [DECIDED]` **BYOK API keys** (Shodan/Censys/Dehashed/…): client keys → operator default → free-source fallback; keys encrypted, per-engagement, never logged.

### 6.2 Reconnaissance (Scout)
- `REC-001 [DECIDED]` Full-surface discovery: web/API **and** edge/VPN appliances, mail, RDP, DB, SSH, cloud storage, DNS, mobile backends.
- `REC-002 [DECIDED]` **Evidence-driven discovery** with response calibration (soft-404/200-empty detection); no blind fixed wordlists.
- `REC-003 [DECIDED]` Stack-aware candidate generation; mutate from real observed endpoints; JS/source-map analysis.
- `REC-004 [DECIDED]` **Origin discovery** behind CDN/WAF, verified via fingerprint match before any direct touch.
- `REC-005 [DECIDED]` **Safe-recon rules**: read-only GET-only discovery; never submit forms, follow state-changing/logout/delete links, trigger reset flows, or cause lockouts.
- `REC-006 [DECIDED]` Own DNS resolver/brute + own CT-log consumer + passive-source resilience layer (cache/retry/circuit-breaker/multi-source; free-source floor).

### 6.3 Validation (Strike)
- `STR-001 [DECIDED]` Credential intelligence **offline-first** (breach-corpus applicability, hash cracking, provenance, ranking).
- `STR-002 [DECIDED]` **Authentication Risk Governor** allows online validation only when explicitly approved and a safe margin below a verified lockout policy is known. If prior failures or lockout state are unknown, default to zero attempts unless an operator approves one exact attempt. Spray shaping reduces but never eliminates lockout risk; MFA or anomaly signals hard-stop.
- `STR-003 [DECIDED]` Authorization differential (IDOR/BOLA) via broker sessions; safe web/service vulnerability validation; distinguish WAF-blocked from not-vulnerable.

### 6.4 Vulnerability intelligence
- `VUL-001 [DECIDED]` Local cache of NVD/CVE + vendor advisories + exploit-db + EPSS + CISA KEV.
- `VUL-002 [DECIDED]` Map to fingerprinted product/version; **probabilistic** applicability confirmed behaviorally where safe (version strings lie; patches are back-ported).

### 6.4a Capability and tool governance
- `CAP-001 [DECIDED]` Every executable capability is present in `config/capability-registry.json`; absence means deny.
- `CAP-002 [DECIDED]` Every entry declares one owning agent, typed adapter, pinned tool/image identity, lifecycle state, risk class, target-identity tier, approval, network path, budget, evidence/oracle, cleanup, and prohibited effects.
- `CAP-003 [DECIDED]` Agents receive capability IDs and typed fields only—never arbitrary shell, tool flags, templates, URLs, callbacks, or raw binaries.
- `CAP-004 [DECIDED]` Tool/template/version changes repeat admission review, fixture/negative-control testing, ARM64 qualification, and digest promotion.
- `CAP-005 [DECIDED]` `PLANNED` and `ON_HOLD` inventory is non-executable. From M2, CI and runtime must load the same registry and default-deny drift.
- `CAP-006 [DECIDED]` Tool output is untrusted evidence. It cannot directly create graph truth or a confirmed/payable finding.
- `CAP-007 [DECIDED]` Scout owns passive/read-only discovery; restricted Strike owns offline/T1 verification in Recon-only; full Strike owns approved T2 validation; Exploit and Post-Exploit remain gated; Report uses offline evidence tooling and requests re-verification through the Conductor.

### 6.5 Controlled exploit (gated, R3+)
- `EXP-001 [DECIDED]` Reviewed capability library only; least-invasive proof; safe oracles preferred over RCE; on hold until the pre-production safety range validates stability.

### 6.6 Reporting (Report)
- `REP-001 [DECIDED]` Independent verification; ≥2 independent evidence families for payable findings.
- `REP-002 [DECIDED]` Severity = CVSS v4 + business-impact overlay + EPSS/KEV + reachability + evidence confidence, evidence-bounded.
- `REP-003 [DECIDED]` Client-runnable reproduction package; remediation guidance; retest hook.
- `REP-004 [DECIDED]` Coverage honesty (assessed/not, blocked, detected, deception encountered).
- `REP-005 [DECIDED]` Detection timeline reconciled post-engagement with the White Cell.

### 6.7 Stealth & OPSEC
- `OPS-001 [DECIDED]` Deterministic suspicion detection + heat state machine (COOL/WARM/HOT/BURNED).
- `OPS-002 [DECIDED]` Jitter engine (log-normal/Poisson/circadian/burst-idle/AIMD/token-bucket).
- `OPS-003 [DECIDED]` De-signaturing egress (browser-like UA/header/TLS-JA3/HTTP2 + pacing).
- `OPS-004 [DECIDED]` BURNED → freeze all target-active work and notify; passive analysis may continue, but a different active path requires operator recovery approval, fresh target identity, and a new lease.
- `OPS-005 [DECIDED]` Honeypot/deception detection module; getting caught is reported as a client win.

### 6.8 Governance & safety
- `GOV-001 [DECIDED]` Deterministic Policy Kernel (fail-closed, un-bypassable, deep parameter/destination scope validation).
- `GOV-002 [DECIDED]` Dual-mode kill switch (freeze vs graceful); dead-man/heartbeat auto-halt; hard financial circuit breaker.
- `GOV-003 [DECIDED]` Deconfliction: 24/7 contact, "is this activity yours?" ledger query, critical-finding immediate disclosure, real-breach handling.

---

## 7. Non-Functional Requirements

- `NFR-001 [DECIDED]` **Do-no-harm:** unified throttle = min(target-health-safe, OPSEC-safe); never crash, lock out, or corrupt.
- `NFR-002 [DECIDED]` **Auditability:** hash-chained ledger; every action replayable; decision provenance for every LLM decision.
- `NFR-003 [DECIDED]` **Evidence integrity:** artifact hashing, content-addressed storage, chain of custody, synced clock, verify routine.
- `NFR-004 [DECIDED]` **Resilience:** external sources are non-blocking and cached; the run never stalls on one slow source.
- `NFR-005 [DECIDED]` **Isolation:** per-capability containers, no Docker socket, L3/L4 egress firewall, per-tenant isolation.
- `NFR-006 [DECIDED]` **Self-security:** per-engagement ephemeral scoped secrets, rotation, dual-control for sensitive ops (BlackBread is itself a high-value target).
- `NFR-007 [DECIDED]` **Resource fit:** runs on a single Oracle Cloud ARM VM (12 GB / 4 OCPU); browser concurrency capped; cloud LLM reasoning.
- `NFR-008 [DECIDED]` **Reproducibility:** NetworkX rebuildable from PostgreSQL; engagements resumable via ledger replay.
- `NFR-009 [DECIDED]` **Governance:** ADR/PRD/rules/skill/registry consistency is CI-tested; required checks cannot use `continue-on-error`, skipped safety tests, or mutable unpinned actions/tool images.
- `NFR-010 [DECIDED]` **Supply chain:** locked Python dependencies, digest-pinned runtime/tool images, SBOM, dependency/secret/container scans, and reviewed update automation.
- `NFR-011 [DECIDED]` **Release evidence:** every milestone publishes a conformance record mapping requirement IDs to commit, tests, open gaps, approver, and timestamp.

---

## 8. Architecture Summary

Five autonomous agents (Scout, Strike, Exploit, Post-Exploit, Report) + deterministic Conductor + Policy Kernel + OPSEC service + Session/Secret Broker service. Canonical state is a hash-chained PostgreSQL event ledger; world state is a temporal evidence-backed attack graph. LLMs reason and plan; deterministic systems execute, enforce safety, and hold memory. Full detail in `ADR-FINAL-002.md`.

---

## 9. Threat-Informed Doctrine (APT references)

BlackBread borrows **discipline and TTPs** (not harm) from four groups: **APT41** (initial-access breadth), **APT29** (identity/trust reasoning, patience, stealth), **Lazarus** (chain composition with a per-edge oracle), **Volt Typhoon** (environment awareness, native read-only living-off-the-land, stealth). Excluded from all: malware, persistence, covert C2, destruction, credential theft-for-keeps, log manipulation. See `ADR-FINAL-002.md` §39.

---

## 10. Success Metrics

- **North-star (MVP):** first cross-verified payable finding accepted by a real client, zero safety incidents.
- **Quality:** false-positive rate; independent-evidence-family coverage; findings reproduced by clients.
- **Stealth:** proportion of engagement time spent COOL; time-to-BURNED; percentage of BURNED events with verified freeze and operator-authorized recovery.
- **Efficiency:** actions per finding; information gain per request; external-source outage tolerance.
- **Safety:** zero lockouts/outages/data-loss; 100% scope adherence; 100% cleanup verification.
- **Business:** engagements sold; Recon-only → higher-tier conversion; per-engagement cost.

---

## 11. Milestones

M0 skeleton → M1 trust spine → M2 capability gateway + OPSEC/egress + passive recon → M3 Scout + Target Identity Guard → M4 restricted/full Strike profiles + first-lane validation → M5 Report + first finding → M6 state/low-and-slow/backup. Releases R0–R5; Exploit (R3) is held until the pre-production safety range validates stability. Milestones are dependency gates, not labels: the release cannot advance with inherited P0/P1 or safety blockers. Detail in `ADR-FINAL-002.md` §35.

Before the first real-target R1 run, required CI checks must be branch-protected; the capability registry must be enforced on the live path; legal/SOW, UU ITE/UU PDP, cross-border processor, breach-data, retention/deletion, incident, responsible-disclosure, and shared-SaaS policies must be approved; ownership evidence and White Cell contacts must be sealed; and kill/dead-man, backup restore, cleanup, and deletion drills must pass.

---

## 12. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Causing an outage/lockout on production | Do-no-harm throttle, safe-recon rules, Authentication Risk Governor, exploit on hold, edge RCE gated |
| Blue-team escalation / legal exposure (covert) | Attested authorization, White Cell deconfliction, sealed manifest, kill switch, dead-man halt |
| Wrong-target / shared-infra action | Target Identity Guard tiers, origin verification, deep scope validation, TOCTOU re-validation |
| Prompt injection from target content | Data/instruction separation, reader/planner split, typed-output backstop, injection test suite |
| LLM refusal of security tasks | Authorization context, task decomposition, open-model routing, weaponization kept out of the LLM |
| External-source flakiness | Resilience layer, caching, free-source floor, build-own resolver/CT |
| Getting detected / IP burned (single egress) | Stealth pacing, de-signaturing, flank-not-push; report detection as a client win |
| Platform itself compromised (high-value target) | Per-engagement ephemeral secrets, isolation, egress firewall, dual-control, hardening |
| False positives from version-only CVE matching | Probabilistic applicability + behavioral confirmation |
| Abuse ("test my competitor") | Evidence-backed manual ownership approval before active contact; automated challenge later; unknown/third-party deny |

---

## 13. Open Questions / Future

Legal/compliance and shared/third-party scope rules are release-entry work, not future debt. Counsel and the operator must close them before R1; this PRD does not invent legal conclusions. Future product work includes continuous re-assessment, compliance-aligned and Bahasa Indonesia reporting, responsible-disclosure automation, richer shared-SaaS handling, dynamic ownership for wildcard/cloud IPs, egress source rotation, and a dedicated local model for sensitive engagements. See `ADR-FINAL-002.md` §38.
