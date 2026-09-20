# Role Contracts

Authority: ADR-FINAL-003.md and ADR-FINAL-005.md through ADR-FINAL-008.md.
Opportunity, specialist, and learning additions follow ADR-FINAL-010.md/011.md only after acceptance
on protected main. Apply their completion criteria to the slice that implements those consumers;
do not require a full learning subsystem for the first passive role loop.

## Role ownership

The five-role goal/boundary table lives in SKILL.md and is always loaded. This reference develops
those roles without defining a second roster or fixed handoff sequence.

Session/secret custody is a deterministic **service**, not an agent.

The signed `CampaignAuthorityEnvelope` is the human-authorized campaign ceiling, not execution
permission. Inside it, agents choose and revise paths without per-hop human approval; every exact
effect still requires a current Policy decision, lease, and `WorkOrder`. Effects outside the envelope
return to the operator rather than being weakened into an in-envelope action.

## APT tradecraft doctrine

Apply these principles to planner/critic reasoning under ADR-FINAL-002.md §§5, 16, and 39,
as amended by the campaign and execution ADRs. They are acceptance qualities, not a fixed playbook.

- **Patience / low-and-slow:** defer and resume useful investigations within budgets and current
  authority; do not hammer unchanged observations. Durable state and fresh-context checks make
  resumption meaningful. Waiting is not failed progress; elapsed time cannot clear a hard stop.
- **Breadth of entry:** maintain multiple independent entry hypotheses and examine authorized
  network/service and edge-appliance terrain as well as web applications. Coverage follows evidence
  and objective relevance; it is not an indiscriminate scan or permission to exploit an appliance.
- **Chain composition:** reason over `primitive → precondition → boundary → next → objective`.
  Each transition needs its own oracle and lineage; a new AccessContext or admitted observation can
  reopen an earlier path. Role order is determined by evidence, not a mandatory five-stage sequence.
- **Environment awareness:** adapt hypotheses to observed stack, trust relationships, and control
  behavior; prefer qualified native read-only capabilities and minimal added tooling when they
  provide the required evidence. Tool availability never establishes authorization.
- **Flanking, not pushing:** when a route is unproductive, reassess authorized techniques, assets,
  and surfaces rather than repeating it. A discovered origin is only another candidate until scope,
  ownership, identity, and route authority are established; a WAF block proves neither safety nor
  permission to bypass it. `BURNED` prohibits autonomous active flanking and requires the existing
  operator-authorized recovery process.

## Recon done right (Scout)
- **Calibrate first:** learn each host's true not-found and found fingerprints (status + length bucket + body-similarity hash + DOM + title + `ETag`/`Last-Modified` + timing). A 200 matching the soft-404 baseline is a NEGATIVE.
- **Observe → derive → targeted probe**, never blind fixed wordlists: parse HTML/JS, extract routes from JS bundles and **source maps**, read `robots`/`sitemap`/`.well-known`/headers/cookies.
- **Stack-aware conventions + mutate from real endpoints** (`/api/v1/users` → `v2`, singular, `/export`).
- **Safe-recon rules:** read-only; GET-only for HTTP discovery. Never submit forms, follow logout/delete/reset/state-changing links, or risk account lockout. DNS/TLS/service observation follows its own registered read-only contract.

## Credentials (Strike) — offline-first + abuse prevention
- OFFLINE credential *intelligence* (breach-corpus applicability, hash cracking, provenance, ranking) — no target contact.
- ONLINE only via the **Authentication Risk Governor** (deterministic) and explicit approval. A low-and-slow spray shape may be safer than brute-force but is not inherently safe. Cap attempts below a verified lockout margin; if prior failures or lockout state are unknown, default to zero unless an operator approves one exact attempt. Hard-stop on lockout/anomaly/heat; MFA present → stop (no MFA bombing).

## Role depth and specialist cognition

| Agent | Must become strong at | Primary quality signal |
|---|---|---|
| Scout | coverage reasoning, continuous terrain diff, HVT candidates, uncertainty-driven discovery | coverage and information gain per request |
| Strike | applicability decomposition, proof-method competition, failure disambiguation, safe variants | discrimination with low false positives and low effect |
| Exploit | one boundary transition, platform/delivery/payload compatibility, successor context, cleanup | verified transition with minimum risk and complete cleanup |
| Post-Exploit | internal rediscovery, privilege/trust reasoning, bounded movement, objective-minimal proof | complete objective path without scope or collection expansion |
| Report | evidence lineage, causal path, counterfactual remediation, minimal cut sets, retest diff | reproducibility, honest coverage, and paths eliminated by fixes |

## Definition of done for an agent
- [ ] Local goal, planner, critic, working memory, typed I/O contract implemented.
- [ ] Cognition loop with novelty gate + per-path progress + budgets.
- [ ] Consumes snapshot-bound opportunities; graph deltas invalidate/reopen only affected paths.
- [ ] Emits typed, evidence-qualified outcomes with failure semantics and learning provenance.
- [ ] Ephemeral specialists, when used, remain role-owned and advisory with no execution authority.
- [ ] All actions go through Conductor + Policy Kernel + OPSEC (no direct execution).
- [ ] Emits/consumes typed events on the hash-chained ledger; graph updates are projections.
- [ ] Safe-recon / do-no-harm rules enforced; OPSEC signals produced and respected.
- [ ] Evidence carries target-identity binding + provenance; findings stay candidates until verified.
- [ ] Registry entry and schemas match the live adapter; denied/unlisted/wrong-agent/direct-shell cases are tested.
- [ ] No release-blocking gap is hidden; requirement status and milestone conformance evidence are updated.
- [ ] Tests: unit + negative + scope-denial + prompt-injection; `ruff`, `mypy`, `pytest --cov`, Bandit, and pip-audit clean.

## APT references (discipline borrowed, harm excluded)
APT41 (initial-access breadth), APT29 (identity/trust, patience, stealth), Lazarus (chain composition + per-edge oracle), Volt Typhoon (environment awareness, native read-only living-off-the-land). Excluded from all: malware, persistence, covert C2, destruction, credential theft-for-keeps, log manipulation. Details in `ADR-FINAL-002.md` §39.

Strike success must not establish a new privilege, authentication, authorization, trust, execution,
or isolation boundary. Reclassify such a proof as Exploit/T3. Report may narrow or reject a producer
claim; screenshots support evidence but cannot replace the declared independent oracle.
