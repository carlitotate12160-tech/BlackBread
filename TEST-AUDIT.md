# BlackBread Test Audit Framework

> Status: DESIGN — prepared before implementation. No code exists yet.
> Purpose: define the complete test surface BlackBread must cover, learned from
> Agent-Alpha's 240-file suite — what Alpha tested well, what Alpha missed, and
> what BlackBread must do differently.

## 1. Alpha's test inventory (what exists)

Alpha has 240 test files across 9 directories. Coverage is broad in some areas,
absent in others.

### 1.1 What Alpha tests well

| Domain | Test count | Quality |
|--------|-----------|---------|
| Scope denial / out-of-scope enforcement | 22 files | Good — per-probe, per-vector |
| Multi-tenant / RLS isolation | 28 files | Good — integration-level RLS guard |
| Deterministic replay / event store | 55 files | Good — event-sourced state tested |
| Soft-404 calibration | 1 file (17.3 KB) | Good — dedicated |
| Credential lockout prevention | 1 file (17 matches) | Good — dedicated |
| Origin binding / origin resolver | 3 files | Good |
| Engagement authorization gate | 3 files | Good |
| Coverage ledger (honest tracking) | 1 file (16 matches) | Good |
| Default-creds false positive rejection | 1 file | Good |
| Beta anti-theater (false success rejection) | 1 file | Good |
| Live-fire scoring | 1 file | Good |
| CVE correlation | 1 file | Present |
| Passive intel | 1 file (66.4 KB) | Large, but unverified depth |

### 1.2 What Alpha tests partially

| Domain | Test count | Gap |
|--------|-----------|-----|
| Hash chain / ledger integrity | 5 files | Shallow — no tamper-detection test, no append-only enforcement test |
| Emergency / kill switch | 3 files | Only revoker + log scrub — no deconfliction protocol, no White Cell escalation |
| Non-web surface (VPN/RDP/SSH/mail/cloud) | 23 files mention | Incidental — only as scope-check fixtures, not as discovery/validation lanes |
| Egress separation | 1 file | One incidental mention — no dedicated target-vs-control-plane test |

### 1.3 What Alpha does NOT test at all (critical gaps)

| Domain | Test count | Risk |
|--------|-----------|------|
| **Prompt injection defense** | 0 dedicated | Target content can manipulate the LLM into emitting malicious proposals. Only redaction is tested. |
| **Deception / honeypot detection** | 0 | Agent cannot distinguish a honeypot from a real target. False findings guaranteed. |
| **Dead-man / heartbeat / auto-freeze** | 0 | If the operator dies or disconnects, the agent runs forever. Safety violation. |
| **Cost circuit breaker** | 0 | LLM/OSINT spend can exhaust the Oracle Cloud budget silently. |
| **BYOK key handling** | 0 | Client-supplied API keys have no encryption, scoping, or leak-prevention tests. |
| **OPSEC temperature FSM** | 0 | No COOL/WARM/HOT/BURNED state machine. No suspicion-signal extraction. No hard-stop test. |
| **Backport / version-lie detection** | 0 | CVE correlation exists but does not test backported patches or misleading banners. |
| **Cleanup / forensic freeze** | 0 (1 incidental) | No test that ephemeral workers are killed, no test that state is frozen on incident. |
| **Circadian jitter / non-uniform timing** | 0 | Stealth pacer exists but no test that timing is non-round, non-uniform, or adaptive. |
| **Target identity tier enforcement (T0-T3)** | 0 | No test that T2/T3 actions require operator confirmation or fresh re-validation. |
| **SaaS provider boundary enforcement** | 0 | No test that shared-SaaS infrastructure is excluded from scope. |
| **Cloud IP reuse / dynamic ownership** | 0 | No test that a reused cloud IP is re-validated for ownership. |
| **Third-party / vendor disclosure workflow** | 0 | No test for coordinated disclosure to upstream vendors. |
| **Async alert for critical findings** | 0 | No test that a critical finding triggers an operator alert. |
| **Re-engagement / continuous reassessment** | 0 | No test that a re-engagement re-validates scope and identity. |

## 2. Alpha's structural mistakes (do not repeat)

| Alpha mistake | Impact | BlackBread rule |
|---------------|--------|-----------------|
| Phase-based test organization (`tests/phase_0/` ... `tests/phase_4/`) | Tests become legacy; phase-exit criteria on paper ≠ evidence passed | Module-based: `tests/policy/`, `tests/opsec/`, `tests/recon/` |
| Coverage not enforced (`--cov-fail-under` absent) | 240 files but unknown real coverage | `--cov-fail-under=80` enforced; 90% for safety-critical |
| McCabe complexity 22 | God-functions pass CI | McCabe max 10, merge block |
| `tmp_*.py` and `tmp_*.sh` in repo root | Dead weight, Lyndon #2 | No scratch files in repo; `.gitignore` blocks `tmp_*` |
| PROTECTED contract test = only 1 file | Typed contracts not frozen | Every typed capability contract gets a frozen test |
| No prompt-injection test suite | LLM is the weakest attack surface | Dedicated `tests/prompt_injection/` suite, regression tests |
| No deception test suite | False findings on honeypots | Dedicated `tests/deception/` suite |
| No dead-man test | Agent runs forever after operator loss | Dedicated `tests/safety/dead_man.py` |
| No cost circuit breaker test | Budget exhaustion | Dedicated `tests/safety/cost_circuit.py` |
| No OPSEC FSM test | No heat state, no hard stop | Dedicated `tests/opsec/temperature_fsm.py` |
| Presence-only tests pass while correctness fails | Lyndon #3 (false success) | Every test must assert effect, not just presence |
| Windows test results accepted | Lyndon #9 | Oracle ARM64 is the only valid test environment |
| 4000-line god object (`autonomous_loop.py`) | Lyndon #6 | 400-line module limit, 50-line function limit |

## 3. BlackBread test taxonomy

Test organization is module-based, not phase-based. Every module maps to a
production code module. Safety-critical modules have higher coverage targets.

```
tests/
  policy/              # Policy Kernel — scope, authorization, target identity
  opsec/               # OPSEC service — heat FSM, jitter, egress, hard stop
  conductor/           # Conductor — orchestration, work orders, handoffs
  ledger/              # Event ledger — hash chain, append-only, replay
  recon/               # Scout — calibration, discovery, passive sources
  strike/              # Strike — validation, credential handling, proof
  report/              # Report — independent verification, severity, coverage
  llm/                 # LLM provider — routing, provenance, refusal handling
  prompt_injection/    # Prompt injection defense — regression suite
  deception/           # Deception analyzer — honeypot/tarpit/honeytoken
  safety/              # Dead-man, cost circuit, cleanup, forensic freeze
  capabilities/        # Capability Gateway — typed contracts, frozen tests
  dashboard/           # Dashboard — attestation, approval queue, kill switch
  governance/          # Architecture governance — layering, size, wiring
  integration/         # End-to-end — full engagement flow, RLS, multi-tenant
  fixtures/            # Shared fixtures, mock targets, lab configs
  PROTECTED/           # Frozen contract tests — never modify
```

## 4. Mandatory test categories (BlackBread must have all)

### 4.1 Policy Kernel tests (`tests/policy/`)

| Test | What it verifies | Coverage target |
|------|-----------------|----------------|
| `test_scope_denial.py` | Out-of-scope host/IP/URL rejected in every parameter position | 95% |
| `test_authorization_gate.py` | No action without valid, unexpired, attested engagement | 95% |
| `test_target_identity_tier.py` | T0 passive / T1 active-read / T2 origin / T3 mutating enforcement | 95% |
| `test_toctou_revalidation.py` | Target identity re-validated inside execution lease | 95% |
| `test_stale_context_rejection.py` | Proposal with stale graph version rejected | 90% |
| `test_saas_boundary.py` | Shared-SaaS infrastructure excluded from scope | 90% |
| `test_cloud_ip_reuse.py` | Reused cloud IP re-validated for ownership | 90% |
| `test_engagement_expiry.py` | Expired engagement auto-freezes all work | 95% |
| `test_attestation_immutability.py` | Web checklist attestation is hash-chained and tamper-evident | 90% |

### 4.2 OPSEC service tests (`tests/opsec/`)

| Test | What it verifies | Coverage target |
|------|-----------------|----------------|
| `test_temperature_fsm.py` | COOL→WARM→HOT→BURNED transitions correct; BURNED freezes all target-active work | 95% |
| `test_suspicion_signals.py` | WAF block, 429, Retry-After, reset, tarpit, soft-block, honeytoken detected | 90% |
| `test_hard_stop.py` | LLM cannot override BURNED; active recovery requires operator approval, fresh identity, and a new lease | 100% |
| `test_jitter_nonuniform.py` | Delays are log-normal, non-round, non-uniform | 90% |
| `test_token_bucket.py` | Per-host and global token buckets enforce rate | 90% |
| `test_aimd_backoff.py` | AIMD backoff respects Retry-After and health signals | 90% |
| `test_circadian_shaping.py` | Timing windows respect configured circadian bands | 85% |
| `test_egress_separation.py` | Target egress and control-plane egress never mix | 95% |
| `test_egress_block.py` | Blocked destination is denied at app and network layer | 90% |
| `test_tls_impersonation.py` | JA3/JA4 fingerprint matches browser profile | 85% |

### 4.3 Prompt injection defense tests (`tests/prompt_injection/`)

This is the suite Alpha completely lacks. It is mandatory.

| Test | What it verifies |
|------|-----------------|
| `test_untrusted_data_isolation.py` | Target content is delimited as data, never parsed as instruction |
| `test_reader_low_privilege.py` | Low-privilege reader extracts structured facts; planner sees facts only |
| `test_injected_proposal_rejected.py` | Compromised LLM can only emit a proposal; deterministic gates deny |
| `test_instruction_in_html.py` | `<system>ignore previous instructions` in HTML is neutralized |
| `test_instruction_in_js.py` | Prompt injection in JavaScript bundles is neutralized |
| `test_instruction_in_header.py` | Injection in response headers is neutralized |
| `test_instruction_in_redirect.py` | Injection in redirect body/Location is neutralized |
| `test_data_delimiter_integrity.py` | Delimiters cannot be broken by target content |
| `test_provenance_tagged.py` | All target-derived content carries provenance tag |
| `test_content_size_limit.py` | Oversized target content is truncated before LLM submission |
| `test_regression_corpus.py` | Known injection payloads from a corpus are all neutralized |

### 4.4 Deception analyzer tests (`tests/deception/`)

Alpha has zero deception tests. BlackBread must detect honeypots.

| Test | What it verifies |
|------|-----------------|
| `test_honeypot_fingerprint.py` | Cowrie/Dionaea/Conpot/T-Pot/Honeyd fingerprints detected |
| `test_accept_any_credential.py` | Accept-any-credential behavior flagged as deception |
| `test_tarpit_timing.py` | Tarpit latency pattern detected |
| `test_honeytoken_detection.py` | Planted credentials/honeytokens flagged |
| `test_impossible_exploit.py` | Overly perfect exploit outcome flagged |
| `test_inconsistent_banner.py` | Banner vs behavior inconsistency flagged |
| `test_isolated_infrastructure.py` | Implausible isolated infrastructure flagged |
| `test_deception_suspicion_flow.py` | DeceptionSuspicion feeds Scout/Strike/Report/OPSEC |
| `test_no_aggressive_on_high_suspicion.py` | High suspicion → no aggressive action |
| `test_deception_reported_honestly.py` | Likely deception reported, not hidden |

### 4.5 Safety tests (`tests/safety/`)

| Test | What it verifies |
|------|-----------------|
| `test_dead_man_heartbeat.py` | Operator heartbeat expiry auto-freezes all active work |
| `test_engagement_expiry_freeze.py` | Engagement TTL expiry auto-freezes |
| `test_cost_circuit_llm.py` | LLM spend over budget → LLM calls stop, agent goes passive |
| `test_cost_circuit_osint.py` | OSINT API spend over budget → external calls stop |
| `test_cleanup_worker_kill.py` | Ephemeral worker killed on lease expiry; process-group kill |
| `test_forensic_freeze.py` | On incident, state frozen (not cleaned) for investigation |
| `test_no_docker_socket.py` | Capability workers cannot access Docker socket |
| `test_resource_limits.py` | CPU/memory/network limits enforced on workers |
| `test_critical_finding_alert.py` | Critical finding triggers async operator alert |
| `test_real_incident_escalation.py` | Real-incident indicator triggers White Cell escalation |

### 4.6 Ledger tests (`tests/ledger/`)

| Test | What it verifies |
|------|-----------------|----------------|
| `test_hash_chain.py` | Each event hash links to previous; chain is tamper-evident | 95% |
| `test_append_only.py` | Past events cannot be modified or deleted | 100% |
| `test_monotonic_ordering.py` | Event timestamps are monotonic | 95% |
| `test_replay_rebuild.py` | Graph rebuilt from ledger replay matches original | 90% |
| `test_graph_version.py` | Proposals reference graph version; stale rejected | 90% |
| `test_artifact_hash.py` | Artifacts are SHA-256 content-addressed | 90% |
| `test_ledger_seal.py` | Periodic ledger seal is verifiable | 85% |

### 4.7 Recon tests (`tests/recon/`)

| Test | What it verifies |
|------|-----------------|
| `test_soft404_calibration.py` | Per-host not-found fingerprint learned; 200-matching-baseline is negative |
| `test_evidence_driven_discovery.py` | Routes derived from real HTML/JS, not blind wordlists |
| `test_js_bundle_extraction.py` | Routes/APIs/params extracted from JS bundles and source maps |
| `test_stack_fingerprint.py` | Tech stack fingerprinted before stack-specific probes |
| `test_path_mutation.py` | Paths mutated from observed endpoints, not generic lists |
| `test_historical_urls.py` | Wayback/Common Crawl used selectively, not exhaustively |
| `test_passive_source_resilience.py` | Circuit breaker, deadline, retry, cache, dedupe per source |
| `test_source_provenance.py` | Every discovered asset carries source provenance |
| `test_coverage_honesty.py` | Inconclusive/blocked/degraded states recorded honestly |
| `test_read_only_enforcement.py` | No form submission, no state-changing links, no lockout risk |
| `test_non_web_surface.py` | VPN/edge, mail, SSH, RDP, DB, cloud storage, DNS discovery |
| `test_cve_backport_detection.py` | Version string treated as probabilistic; backport detection |
| `test_cve_version_lie.py` | Misleading banner does not produce false finding |

### 4.8 Strike tests (`tests/strike/`)

| Test | What it verifies |
|------|-----------------|
| `test_validation_vs_scanner.py` | Scanner match is not a finding; applicability confirmed |
| `test_least_invasive_proof.py` | Exposure + applicability + safe oracle preferred over RCE |
| `test_credential_applicability.py` | Credential leak ≠ valid credential; applicability ranked |
| `test_auth_risk_governor.py` | Online attempts ≤ min(config, 3); below lockout threshold |
| `test_mfa_stop.py` | MFA-protected account → stop, no MFA bombing |
| `test_lockout_stop.py` | Lockout signal → immediate stop |
| `test_spray_not_brute.py` | 1 password × many accounts, not many passwords × 1 account |
| `test_offline_credential_analysis.py` | Breach corpus, hash analysis, provenance, ranking — no target contact |
| `test_secret_redaction.py` | No raw secrets in events, graph, logs, prompts, or artifacts |
| `test_independent_evidence.py` | At least two independent evidence families where feasible |

### 4.9 Report tests (`tests/report/`)

| Test | What it verifies |
|------|-----------------|
| `test_independent_verification.py` | Report re-verifies finding independently of Scout/Strike |
| `test_severity_evidence_bounded.py` | Severity rated for proven impact only; potential labeled separately |
| `test_cvss_calculator.py` | CVSS v4.0 vector calculated deterministically |
| `test_business_impact_overlay.py` | Business impact mapped to client crown-jewels |
| `test_reproduction_package.py` | Client-runnable reproduction package generated |
| `test_no_raw_secrets_in_report.py` | Sensitive values redacted in report |
| `test_coverage_honesty_report.py` | Blocked/detected/deception/inconclusive reported truthfully |
| `test_detection_timeline.py` | Detection/heat timeline included as proxy, not guarantee |
| `test_target_identity_binding.py` | Finding carries target identity binding |
| `test_chain_of_custody.py` | Artifact chain-of-custody metadata present |

### 4.10 LLM provider tests (`tests/llm/`)

| Test | What it verifies |
|------|-----------------|
| `test_provider_routing.py` | Router selects provider by role/sensitivity/cost/health |
| `test_openai_compatible_adapter.py` | OpenRouter/DeepSeek/Qwen adapter works |
| `test_structured_output.py` | Pydantic validation + repair on LLM output |
| `test_refusal_decomposition.py` | Refusal handled by task decomposition, not jailbreak |
| `test_provenance_logged.py` | Provider/model/version/prompt-hash/input-hash/output/tokens/cost/timestamp |
| `test_no_raw_secret_in_prompt.py` | Secrets never appear in LLM prompts |
| `test_model_router_failover.py` | Provider failure → failover to next provider |

### 4.11 Capability Gateway tests (`tests/capabilities/`)

| Test | What it verifies |
|------|-----------------|
| `test_typed_contract.py` | Every capability has typed input/output schema |
| `test_eligible_agents.py` | Only eligible agents can invoke a capability |
| `test_risk_class.py` | Risk class enforced per capability |
| `test_budget_enforcement.py` | Per-capability budget enforced |
| `test_no_direct_execution.py` | LLM output never directly executes |
| `test_process_group_kill.py` | Worker killed with process group on lease expiry |
| `test_frozen_contract.py` | PROTECTED contract tests for every typed capability |

### 4.12 Dashboard tests (`tests/dashboard/`)

| Test | What it verifies |
|------|-----------------|
| `test_no_self_registration.py` | No public signup; access by invitation only |
| `test_attestation_checklist.py` | Web checklist captures attesting user, timestamp, scope, mode, objectives, stop conditions, deconfliction contact |
| `test_attestation_hash_chained.py` | Attestation stored immutably in ledger |
| `test_approval_queue.py` | T2/T3 actions queue for operator approval |
| `test_kill_switch.py` | Kill switch immediately freezes all active work |
| `test_byok_key_encryption.py` | Client API keys encrypted in vault, scoped per engagement |
| `test_byok_no_leak.py` | BYOK keys never in logs, prompts, graph, or artifacts |
| `test_byok_resolution.py` | Client key → operator key → free-source fallback |
| `test_engagement_mode_enforcement.py` | Recon-only permits only restricted offline/T1 Strike capabilities; Recon+Validate blocks Exploit |

### 4.13 Governance tests (`tests/governance/`)

| Test | What it verifies |
|------|-----------------|
| `test_layering.py` | No circular imports; module dependency graph is a DAG |
| `test_size_ratchet.py` | Module ≤400 lines; function ≤50 lines; McCabe ≤10 |
| `test_wiring_gate.py` | Every capability is wired into the autonomous path, not island |
| `test_no_scratch_files.py` | No `tmp_*` or debug scripts in repo |
| `test_no_duplicate_types.py` | One class per concept; no duplicate canonical types |
| `test_no_god_object.py` | No module exceeds responsibility boundary |
| `test_doc_status_consistency.py` | ADR/PRD/rule/skill consistent with each other |

### 4.14 Integration tests (`tests/integration/`)

| Test | What it verifies |
|------|-----------------|
| `test_full_engagement_recon_only.py` | E2E: attestation → Scout → restricted offline/T1 Strike → Report; full Strike capabilities denied |
| `test_full_engagement_validate.py` | E2E: attestation → Scout → Strike → Report |
| `test_rls_isolation.py` | Multi-tenant RLS enforced; tenant A cannot see tenant B |
| `test_postgres_durability.py` | State survives restart; graph rebuilt from ledger |
| `test_conductor_auth_path.py` | Every execution path passes through Policy Kernel |
| `test_opsec_pipeline.py` | Suspicion signal → heat transition → throttle → hard stop |
| `test_prompt_injection_e2e.py` | Injected target content → neutralized → no malicious action |
| `test_deception_e2e.py` | Honeypot target → detected → reported as deception |
| `test_dead_man_e2e.py` | Heartbeat expiry → auto-freeze → no further actions |
| `test_cost_circuit_e2e.py` | Budget exhausted → LLM/OSINT stop → passive-only |

## 5. Test pyramid

```
                    ┌─────────────────┐
                    │  E2E / Live-fire │  ~10 tests  (real lab targets, Oracle ARM64)
                    └────────┬────────┘
                  ┌──────────┴──────────┐
                  │  Integration tests  │  ~20 tests  (Postgres, RLS, full flow)
                  └──────────┬──────────┘
                ┌────────────┴────────────┐
                │  Contract tests (frozen) │  ~30 tests  (typed capability schemas)
                └────────────┬────────────┘
              ┌──────────────┴──────────────┐
              │  Unit tests (per module)    │  ~200+ tests  (deterministic, fast)
              └─────────────────────────────┘
```

- **Unit tests**: deterministic, no network, no LLM, no DB. Fast (<2s total).
- **Contract tests**: frozen, never modified. Schema stability enforcement.
- **Integration tests**: real Postgres + Redis, no real targets, no real LLM.
- **E2E / live-fire**: real lab targets on Oracle ARM64, real LLM API. Slow,
  run nightly or on-demand. Never on Windows.

## 6. CI enforcement (binding)

```yaml
# Blocking checks (every PR):
- ruff check                    # lint, mccabe ≤10
- ruff format --check           # format
- mypy --strict                 # type check
- pytest --cov=blackbread --cov-fail-under=80
- bandit -r blackbread/         # SAST
- pip-audit                     # dependency CVEs
- gitleaks                      # secret scanning

# Safety-critical coverage (separate check):
- pytest tests/policy/ tests/opsec/ tests/safety/ tests/ledger/ --cov-fail-under=90

# Nightly (security-audit.yml):
- trivy image scan
- syft SBOM
- nuclei templates (lab targets only)

# AI review:
- CodeRabbit auto-review with path-specific instructions
```

## 7. Anti-patterns that must fail in CI

| Anti-pattern | CI gate that catches it |
|---------------|------------------------|
| Spaghetti function (>50 lines) | `ruff` mccabe >10 → merge block |
| God module (>400 lines) | `tests/governance/test_size_ratchet.py` |
| Circular import | `tests/governance/test_layering.py` |
| Scratch file in repo | `tests/governance/test_no_scratch_files.py` |
| Duplicate canonical type | `tests/governance/test_no_duplicate_types.py` |
| Unwired capability (island) | `tests/governance/test_wiring_gate.py` |
| Presence-only test (Lyndon #3) | Code review + CodeRabbit path instructions |
| Coverage <80% | `--cov-fail-under=80` |
| Safety-critical coverage <90% | Separate `--cov-fail-under=90` gate |
| Raw secret in prompt/log | `gitleaks` + `tests/llm/test_no_raw_secret_in_prompt.py` |
| Prompt injection regression | `tests/prompt_injection/test_regression_corpus.py` |

## 8. Test data and lab targets

Lab targets are Docker Compose stacks on Oracle ARM64, used only for E2E and
live-fire tests. Never for unit tests.

| Lab | Purpose |
|-----|---------|
| `labs/web_exposure/` | Public artifact exposure, soft-404, path calibration |
| `labs/secret_leak/` | JS secret leak, env file exposure, backup file |
| `labs/origin_bypass/` | CDN-fronted origin, origin-direct reach |
| `labs/honeypot/` | Cowrie-like honeypot for deception detection |
| `labs/wp_stack/` | WordPress with known 1-day misconfig |
| `labs/odoo_stack/` | Odoo with default-creds and DB manager |
| `labs/edge_appliance/` | VPN/SSH/RDP mock for non-web surface |
| `labs/saas_boundary/` | Shared-SaaS infrastructure for scope denial |

Each lab has a `ground_truth.yaml` that defines what the agent SHOULD find and
what it should NOT find. Live-fire scoring compares agent output to ground truth.

## 9. What BlackBread must test that Alpha never did (summary)

These are the non-negotiable additions. Alpha's 240 files missed all of these:

1. **Prompt injection regression corpus** — target content is the primary attack
   surface against the agent itself.
2. **Deception/honeypot detection** — without this, every honeypot is a false
   finding.
3. **Dead-man heartbeat auto-freeze** — without this, the agent runs unbounded
   after operator loss.
4. **Cost circuit breaker** — without this, LLM/OSINT spend exhausts the budget
   silently.
5. **OPSEC temperature FSM** — without this, there is no stealth state machine
   and no hard stop.
6. **BYOK key handling** — without this, client API keys leak.
7. **Egress separation enforcement** — without this, target traffic and
   control-plane traffic mix.
8. **Backport/version-lie detection** — without this, CVE correlation produces
   false findings from misleading banners.
9. **Target identity tier enforcement (T0-T3)** — without this, origin-direct
   and mutating actions have no gate.
10. **Cleanup and forensic freeze** — without this, ephemeral workers leak and
    incident state is lost.
11. **SaaS boundary enforcement** — without this, shared infrastructure is
    attacked out of scope.
12. **Cloud IP reuse re-validation** — without this, dynamic cloud IPs break
    scope binding.
13. **Circadian jitter / non-uniform timing** — without this, the agent has a
    detectable timing signature.
14. **Async critical-finding alert** — without this, critical findings sit
    unread.
15. **Third-party/vendor disclosure workflow** — without this, upstream vendors
    are not notified.

## M1 ledger slice verification matrix

| Contract | Positive evidence | Negative evidence | Status |
|---|---|---|---|
| Tenant-bound append/replay | independent tenant chains and scoped verification | wrong-tenant append/verify denied; composite FK rejects tenant drift | VERIFIED |
| Serialized monotonic sequence | ten concurrent appenders produce contiguous sequence | missing middle event fails replay | VERIFIED |
| Immutable event envelope | payload, metadata, sensitivity, and redaction references are hash-bound | payload/link/hash/label/reference tampering detected | VERIFIED |
| Database append-only enforcement | migration installs mutation and truncate triggers | UPDATE, DELETE, and TRUNCATE rejected | VERIFIED |
| Canonical and versioned hashing | stable UTC/JSON hashing with SHA-256 version 1 | naive time, non-finite numbers, non-JSON values, unknown hash scheme rejected | VERIFIED |
| R0 trust spine | ledger primitive only | `LEDGER-GAP-001` blocks graph, Conductor, Policy Kernel, leases, kill-switch, and RLS claims | OPEN |

