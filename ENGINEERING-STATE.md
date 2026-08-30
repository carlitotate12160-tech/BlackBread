# BlackBread Engineering State

This file records the repository owner's selected work sequence. It is not proof of implementation
and never overrides live GitHub, accepted architecture, delivery policy, tests, or open gaps.

## State metadata

* **State:** ACTIVE
* **Current milestone:** M1 — Trust Spine
* **Last verified:** 2026-08-30 UTC
* **Protected main baseline:** `4bf2942` (coordination update after PR #31 and PR #32)
* **Last merged PR:** `#33` (chore: update ENGINEERING-STATE.md after PR #31 and PR #32 merge)
* **Active ruleset:** `main-branch-protection` (`21644438`)
* **Contractual gate:** first-party CI (`quality`, `tests`, `security`, `governance`) +
  `GitGuardian Security Checks` + review-thread resolution + branch currency (live ruleset
  conformance verified by GOV-GAP-001)

These values are checkpoints to verify, not facts to trust without querying live GitHub.

## Current decision

Two governance PRs merged in sequence:

* **PR #31** (Alpha): protected-base size budgets — `quality-budget` workflow, `size_budget.py`
  module, `check_size_budget.py` script, `quality-budgets.json` config. Legacy oversize exceptions
  derived from protected base; cap increases fail closed.
* **PR #32** (Devin): restored ci-ok aggregator, CodeRabbit auto-trigger, banned patterns (13
  tests), AI-slop detection (5 tests), diff budget, advisory AI review policy with safety-critical
  binding, GAP-REGISTER sync, ci-ok governance tests (3 tests in `test_ci_ok_aggregator.py`).

The repository now has both the protected-base size budget system (PR #31) and the Decepticon-style
quality gates (PR #32): banned patterns, AI-slop signatures, diff budget, ci-ok aggregator, and
CodeRabbit auto-trigger.

## What is now live on main

### From PR #30 (anti-spaghetti + supply-chain gates)

* Production module ≤400 lines, function ≤50 lines, McCabe ≤10
* Test module ≤500 lines with shrink-only exceptions
* No circular imports, no duplicate test names
* Docker images digest-pinned, GitHub Actions SHA-pinned
* No floating version constraints
* Active capabilities must have supply-chain pins

### From PR #31 (protected-base size budgets)

* `quality-budget` workflow (`pull_request_target`, read-only, base-controlled)
* `src/blackbread/governance/size_budget.py` — pure policy module
* `scripts/check_size_budget.py` — CLI evaluator
* `config/quality-budgets.json` — caps config
* Legacy oversize exceptions derived from protected base SHA
* Cap decreases allowed; cap increases denied

### From PR #32 (ci-ok + quality gates)

* `ci-ok` aggregator job in `ci.yml` (aggregates quality, tests, security, governance)
* `ci-ok` fails on any non-success result (failure, cancelled, skipped)
* `coderabbit-trigger.yml` — auto-trigger CodeRabbit via PAT comment (advisory, non-blocking)
* `test_banned_patterns.py` — 13 tests: bare except, except-pass, type-ignore, noqa, print,
  suppressed returns, NotImplementedError, TODO, if-true-else-false, vague names, flag words,
  speculative kwargs, diff budget
* `test_ci_ok_aggregator.py` — 3 tests: ci-ok exists with `if: always()`, needs all required jobs,
  fails on non-success
* Diff budget: ≤400 runtime lines, ≤10 runtime files (excludes docs/config)
* Advisory AI review policy with safety-critical binding (CodeRabbit FULL required for
  safety-critical paths; Qodo fallback for non-safety-critical only)
* `GAP-REGISTER.md` updated to reference ci-ok aggregator
* `.github/agent-delivery.json` updated: required_status_checks = ci-ok + GitGuardian

### What is NOT yet live

* `quality-budget` is NOT a required status check in the live ruleset (only `quality`, `tests`,
  `security`, `governance`, `GitGuardian Security Checks` are required)
* `ci-ok` is NOT yet a required status check in the live ruleset (same four individual checks
  remain required)
* CodeRabbit auto-trigger workflow has not been verified end-to-end (PAT scope issue: needs
  `pull-requests: write` for `gh pr comment`)
* CodeRabbit skips auto-review for repos with fewer than 10 stars (manual trigger required)
* Test quality bar (mock SUT, tautological tests, vague test names, skip/flaky/pragma) — NOT yet
  implemented
* Self-review checklist — NOT yet in PR template
* End-to-end verification statement — deferred until runtime exists

## Active selected slice

* **ID:** PR-M1.3a
* **Title:** Deterministic ScopeRoot Graph Projection + Replay/Rebuild Spine
* **State:** ACTIVE
* **Owner:** trust-spine
* **Purpose:** prove the ledger-derived graph architecture for `engagement.attested` through one
  independently verified committed snapshot, deterministic durable `ScopeRoot` projection,
  NetworkX rebuild, and versioned state root.
* **Selection:** the repository owner selected this slice ahead of PR-Q2/Q3. That sequencing change
  does not waive governance, architecture, isolation, evidence, or release blockers.

### Bounded scope and non-goals

This slice admits only positive attested scope as authoritative `ScopeRoot` nodes. It does not create
observed assets or edges, implement the broader Attack Graph, resume target-facing capabilities,
implement Q2/Q3/Q4, close `GOV-GAP-001` or `LEDGER-GAP-001`, or advance M1/R0.

No following implementation slice is selected. A fresh owner decision and live revalidation are
required after PR-M1.3a.

## Open blockers

The following remain OPEN unless live closure evidence proves otherwise:

* GOV-GAP-001 (live ruleset conformance is not yet verified against the machine contract —
  `ci-ok` not yet required in live ruleset)
* LEDGER-GAP-001 (R0 trust-spine integration remains incomplete)

Former GOV-GAP-002 through GOV-GAP-005 are CLOSED (WITHDRAWN) with the AI-review gate removal; see
GAP-REGISTER.md. No session may infer closure from this work-state document.

## Update protocol

Update this file when:

* the selected slice changes;
* an in-flight PR is merged, closed, superseded, or materially rescoped;
* a prerequisite or blocker changes;
* live evidence invalidates the expected checkpoint;
* the repository owner selects the following slice.

Do not update it merely to make implementation appear complete. Completion remains proven by live
code, migrations, tests, CI, review evidence, and release records.
