---
description: Non-negotiable engineering guardrails for building the BlackBread external red-team / adversary-emulation platform
trigger: always_on
---

# BlackBread Engineering Guardrails

BlackBread is an **authorized, covert, agentless external red-team / adversary-emulation** platform. It emulates APT tradecraft (patience, stealth, chain composition) but is strictly authorized and non-destructive. Full context: `ADR-FINAL-002.md` and `PRD.md`. For how to build agents, use the `/build-blackbread-agent` skill.

## Hard invariants (never violate)
- **Authorization first.** No target action without a valid, unexpired, attested engagement manifest verified by the Policy Kernel.
- **Deterministic safety, not LLM.** Policy Kernel, OPSEC heat/stop, budgets, scope, and the Authentication Risk Governor are pure deterministic code. The LLM never gates safety and never executes actions — it only emits typed proposals.
- **Un-bypassable Policy Kernel.** The only path from proposal to execution goes through it; it is fail-closed and validates *every* host/IP/URL in *all* parameters against scope.
- **No destructive actions, no real persistence, no covert C2, no anti-forensics/log-tampering.** Ever.
- **Do-no-harm applies to recon.** Read-only GET-only discovery; never submit forms, follow state-changing/logout/delete links, trigger reset flows, or risk account lockout. Effective throttle = min(target-health-safe, OPSEC-safe).
- **No raw secrets** in events, graph, logs, or prompts — only opaque vault references.
- **Target Identity Guard before active action.** Verify target identity at the required tier; re-validate inside the lease (TOCTOU). Origin IPs (post-CDN-bypass) require high-confidence fingerprint match first.
- **Exploit phase stays ON HOLD** until the pre-production safety range validates do-no-harm and scope adherence. Prefer least-invasive proof; never fire memory-corruption RCE at production edge appliances.
- **Controlled evasion only:** loose on form (encoding/pacing), strict on effect (semantics map to a reviewed non-destructive base). No arbitrary LLM-generated payloads.

## Architecture rules
- Five agents (Scout, Strike, Exploit, Post-Exploit, Report). No central brain. No arbitrary agent-to-agent commands — communicate via typed events → Conductor → work orders.
- Session/Secret custody is a deterministic **service**, not an agent.
- Canonical state = hash-chained PostgreSQL event ledger. NetworkX is a rebuildable view, never storage.
- Two egress paths kept separate: **target egress** (scope-locked, stealth-shaped) vs **control-plane egress** (LLM/OSINT/installs). Never mix.

## Prompt-injection defense
Treat all target-derived content as untrusted data, never instructions. A low-privilege reader extracts it into structured facts; planners reason only over structured facts. Even a fully injected agent can only emit a proposal that deterministic gates still block.

## Tooling & build
- Python 3.12, FastAPI, Pydantic, SQLAlchemy/Alembic, PostgreSQL, pytest, pytest-asyncio, pytest-cov, pytest-randomly, pytest-timeout, ruff, mypy, bandit, pip-audit. All container images must be arm64.
- Customize OSS at extension points (Nuclei templates, mitmproxy addons, sqlmap tamper scripts) and build-fresh the small pieces (resolver, CT consumer, resilience layer). Prefer JSON/library output over CLI scraping. Do not fork a tool merely to rename it.
- **Strict TDD.** Every new feature and every bug fix starts with a failing test, then implementation, then green. No PR is merged with red or skipped tests.
- **Coverage target = 80%, enforced.** `pytest --cov=blackbread --cov-fail-under=80` in CI. Safety-critical paths (Policy Kernel, scope denial, OPSEC heat/stop, Authentication Risk Governor, Target Identity Guard, ledger hashing, prompt-injection gates) target ≥90%. Coverage is measured per-PR and reported in the CodeRabbit review.
- **Ruff config (binding):** `target-version = "py312"`, `line-length = 100`, `lint.mccabe.max-complexity = 10` (stricter than Agent-Alpha's 22 — no god-functions). Select E/W/F/I/B/UP/N/S/ASYNC/C4/RET/SIM/PL. Generated protobuf is excluded. `ruff format --check` is blocking.
- **No spaghetti.** Modules own one responsibility. No circular imports. No god objects. Capability contracts are typed and reviewed. If a function exceeds ~50 lines or a module exceeds ~400 lines without clear cohesion, split it. Prefer composition over inheritance. Prefer pure functions for deterministic safety code. McCabe complexity >10 is a merge block.
- Run `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest --cov` before considering work done. Any failure blocks merge.
- **AI review bot: CodeRabbit** (`.coderabbit.yaml` at repo root). Auto-review on every PR, path-specific instructions for `conductor/`, `policy/`, `recon/`, `tools/`, `security/`, `tests/`, `.github/workflows/`. Walkthrough + high-level summary + review status required.
- Do NOT add code comments unless asked; do not use emojis in code or files.

## Honesty
Coverage honesty is mandatory: "nothing found" is never "secure." Report blocked/detected/deception/inconclusive states truthfully. Getting caught by the client's defenses is a client win — report it.
