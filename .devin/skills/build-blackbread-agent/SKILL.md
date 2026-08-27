---
name: build-blackbread-agent
description: Guidance for building and extending BlackBread's autonomous agents (Scout, Strike, Exploit, Post-Exploit, Report) so they operate with APT operator tradecraft while positioned as an authorized external red-team exploitation platform. Use when implementing an agent, its cognition loop, capabilities, OPSEC behavior, or wiring it into the Conductor / Policy Kernel / ledger.
triggers:
  - user
  - model
---

# Building a BlackBread Agent

BlackBread is an **authorized, covert, agentless external red-team / adversary-emulation** platform. Agents must *think and act like an APT operator* — patient, stealthy, objective-driven, chain-composing — while staying strictly authorized and non-destructive. Read `ADR-FINAL-002.md` for full architecture; obey `.devin/rules/blackbread.md` at all times.

## Golden rule
**LLM = reasoning cortex. Deterministic code = skeleton, muscle, memory, and safety.** The LLM proposes; it never executes actions and never gates safety. This split is what makes APT-operator behavior both feasible and safe.

## The five agents (build each with one clear goal)
| Agent | Goal | Never |
|-------|------|-------|
| Scout | Discover evidence-backed primitives across the full surface (web + edge/VPN/mail/DB/cloud) | test creds, exploit, mutate state, confirm findings |
| Strike | Confirm a primitive is genuine/applicable at minimum risk | broad-spray, unbounded attempts, destructive actions |
| Exploit (ON HOLD) | One controlled, approved, verifiable boundary proof | arbitrary payloads, crash production, persist |
| Post-Exploit | One separately approved impact objective | dump creds, lateral movement, durable access |
| Report | Independently verify; downgrade unsupported claims | assert impact beyond proof |

Session/secret custody is a deterministic **service**, not an agent.

## Cognition loop (implement per agent — OODA)
```
1 Observe  → read a retrieval slice of the verified graph (not raw LLM memory)
2 Orient   → LLM planner emits typed candidate actions:
             {proves, precondition, info_gain, risk, cost, opsec_noise}
3 Critic   → challenge evidence / duplication / scope / oracle / stealthier alternative
4 Rank     → deterministic formula over the LLM's estimates
5 Decide   → emit typed proposal → Conductor + Policy Kernel + OPSEC gate it
6 Act      → executor runs ONE typed capability via the OPSEC egress gateway
7 Interpret→ LLM proposes; deterministic oracle + evidence rules confirm/reject
8 Update   → write typed events to the hash-chained ledger; loop
```
**Anti-loop (mandatory — this is what alpha lacked):**
- Novelty/dedup gate: hash `(capability, target, params)`; reject near-duplicates.
- Per-path progress: prune a path to `INCONCLUSIVE` after N steps with no info gain.
- Ranked frontier + hierarchical budgets (path / agent / engagement); global stop when the frontier is empty.

## APT tradecraft to encode (in planner/critic prompts + deterministic services)
- **Patience / low-and-slow:** pace under detection thresholds; dwell and resume, don't hammer.
- **Breadth of entry:** keep multiple independent hypotheses; prioritize exposed reusable primitives; cover edge appliances, not just web.
- **Chain composition:** every graph edge has its own oracle; `primitive → precondition → boundary → next → objective`.
- **Environment awareness:** fingerprint the stack, use native read-only capabilities, minimal added tooling.
- **Flanking, not pushing:** on suspicion, change technique/asset/surface; go to the verified origin instead of the WAF-fronted host.

## Recon done right (Scout) — avoid alpha's "everything is 404"
- **Calibrate first:** learn each host's true not-found and found fingerprints (status + length bucket + body-similarity hash + DOM + title + `ETag`/`Last-Modified` + timing). A 200 matching the soft-404 baseline is a NEGATIVE.
- **Observe → derive → targeted probe**, never blind fixed wordlists: parse HTML/JS, extract routes from JS bundles and **source maps**, read `robots`/`sitemap`/`.well-known`/headers/cookies.
- **Stack-aware conventions + mutate from real endpoints** (`/api/v1/users` → `v2`, singular, `/export`).
- **Safe-recon rules:** read-only GET-only; never submit forms, follow logout/delete/reset/state-changing links, or risk account lockout.

## Credentials (Strike) — offline-first + abuse prevention
- OFFLINE credential *intelligence* (breach-corpus applicability, hash cracking, provenance, ranking) — no target contact.
- ONLINE only via the **Authentication Risk Governor** (deterministic): prefer spray (1 pw × many accounts) over brute; cap attempts = `min(config ≤ 3, safe margin below lockout)`; long delays; hard-stop on lockout/anomaly/heat; MFA present → stop (no MFA bombing).

## OPSEC service (deterministic danger-stop)
- Extract suspicion signals per response (WAF blocks/challenges, 429/`Retry-After`, resets, latency/tarpit, soft-blocks, honeytoken hits, new WAF, White Cell escalation).
- Heat FSM `COOL → WARM → HOT → BURNED`; throttle = min(health-safe, OPSEC-safe).
- Jitter: log-normal delays + Poisson arrivals + circadian shaping + burst-idle + AIMD backoff + token buckets + order shuffle; avoid uniform patterns (self-signature).
- **The LLM cannot override the hard stop.** BURNED → auto passive-only + notify, then flank after cooldown.
- De-signature all tool traffic centrally (browser-like UA/header order/**TLS JA3**/HTTP2 + pacing) via the egress proxy; controlled evasion is loose-on-form / strict-on-effect.

## Target Identity Guard (before any active action)
Bind evidence to hostname/IP/cert/app/tenant/time; classify ownership; enforce tiers T0 (passive) / T1 (active read-only) / T2 (origin-direct) / T3 (mutating, fresh re-validation in lease). MVP: T0/T1 auto, T2/T3 operator-confirm. Verify a discovered origin by fingerprint match before touching it.

## Capabilities & tools
- Every tool runs behind a typed Capability Gateway contract (eligible agents, risk class, input/output schema, limits, evidence requirements) and the single OPSEC egress.
- Customize OSS at extension points (Nuclei templates, mitmproxy addons, sqlmap tamper scripts); build-fresh the small high-value pieces (DNS resolver/brute, CT-log consumer, passive-source resilience layer). Prefer JSON/library output over CLI scraping.
- Browser: utls/curl-impersonate fast path; Camoufox heavy path (cap concurrency). Never build a browser engine.

## LLM integration
- One `LLMProvider` abstraction; OpenAI-compatible adapter covers OpenRouter/DeepSeek/Qwen/local; deterministic router by role/sensitivity/cost/health. MVP: OpenRouter.
- Structured/schema-constrained output (Pydantic validate + repair). Log model + version + prompt hash + inputs + output as decision provenance.
- Reduce refusals legitimately: authorization context + task decomposition (narrow analytical sub-tasks, never "hack X") + open-model routing + keep weaponization out of the LLM. No jailbreaks.

## Prompt-injection defense (build into every LLM call)
Target content is untrusted DATA, never instructions. A low-privilege reader extracts it into structured facts; planners reason only over structured facts. The typed-output backstop means an injected agent can at most emit a proposal that deterministic gates still deny. Tag provenance; run the injection test suite.

## Definition of done for an agent
- [ ] Local goal, planner, critic, working memory, typed I/O contract implemented.
- [ ] Cognition loop with novelty gate + per-path progress + budgets.
- [ ] All actions go through Conductor + Policy Kernel + OPSEC (no direct execution).
- [ ] Emits/consumes typed events on the hash-chained ledger; graph updates are projections.
- [ ] Safe-recon / do-no-harm rules enforced; OPSEC signals produced and respected.
- [ ] Evidence carries target-identity binding + provenance; findings stay candidates until verified.
- [ ] Tests: unit + scope-denial + prompt-injection; `ruff`, `mypy`, `pytest` clean.

## APT references (discipline borrowed, harm excluded)
APT41 (initial-access breadth), APT29 (identity/trust, patience, stealth), Lazarus (chain composition + per-edge oracle), Volt Typhoon (environment awareness, native read-only living-off-the-land). Excluded from all: malware, persistence, covert C2, destruction, credential theft-for-keeps, log manipulation. Details in `ADR-FINAL-002.md` §39.
