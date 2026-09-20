# ADR and skill alignment qualification

State: QUALIFICATION_REQUIRED. This document is a handoff, not release evidence.

Protected base reviewed: `1d44577ba2f6220473d8e2b5d8ad7b90f65ff08a`.
The exact candidate is the commit containing this record on `docs/autonomous-learning-architecture`.
Record its full SHA before running qualification; never substitute a moving branch during a run.
PR #98 was open at head `c16370da8c1d28261aa27967d5d9fc63a82f6ae1`, with no overlapping files.
Ruleset 21644438 was active, with no bypass actors; no mergeability claim is made for either branch.

## Bounded change and review

This is a documentation/derived-contract alignment. No production source, migration, capability
registry, release gate, dependency pin, or engineering-state checkpoint is changed. M1.4d remains
the selected runtime slice. ADR 010/011 record agreed design; protected-main acceptance and runtime
implementation remain separate. No target-facing behavior is activated and no gap is closed.

- Build skill: restore always-loaded product/role anchors; route four responsibility references.
- Domain doctrine: patience, breadth, per-edge chain proof, environment awareness, and authorized
  alternatives remain explicit; OPSEC holds and BURNED do not become autonomous resume permission.
- Engineering skill: route prospective knowledge/learning decisions through existing architecture
  lenses; preserve delivery ownership and existing preflight requirements.
- ADR 003: bound ephemeral specialists to advisory role-owned cognition.
- ADR 004/006: make ready reservation a prerequisite of the first agent proposal; distinguish the
  historical roadmap checkpoint from the live engineering-state manifest.
- ADR 005/007/008/009: reviewed; retain campaign ceiling, independent adaptive-artifact qualification,
  dedicated bounded movement, and public N-Day intelligence separation. No semantic rewrite needed.
- ADR 010: deterministic compilation with advisory output, incremental frontier, uncertainty,
  role reasoning, and no execution authority in knowledge.
- ADR 011: four memory planes, typed outcomes, attempted/unattempted distinction, contextual priors,
  privacy-qualified promotion, offline evaluation, and no autonomous production self-modification.
- PRD/rules/AGENTS/README/gaps: align references and requirement IDs; preserve DECIDED status.

## Evidence already obtained

- Existing documentation/delivery assertions executed directly using Python: 19 passed after final
  routing hardening. This is not a pytest session or a full governance-suite result.
- Read-only independent skill scenarios: waiting evidence, blocked/alternative surface, generated
  candidate, and historical success without current evidence produced coherent bounded decisions.
- Relative links and whitespace checked locally. These do not prove runtime security or release readiness.
- Full environment setup failed: `uv sync --locked` timed out fetching dependencies from PyPI/
  files.pythonhosted.org. Offline sync also failed because required packages were absent from cache.
  No dependency pins, tests, or preflight gates were weakened to proceed.

## Runner instructions

Use an authorized engineering environment with the repository's declared Python/dependencies and
test services. Preserve secrets in that environment; do not print or upload them. Run on the exact
candidate SHA and stop on mismatch, missing service, or any need to edit the candidate.

1. Record `git rev-parse HEAD` and confirm the candidate SHA.
2. Run `uv sync --locked`.
3. Run `uv run pytest tests/governance/test_external_to_objective_adrs.py tests/governance/test_delivery_contract.py --no-cov`.
4. Run `uv run pytest tests/governance --no-cov`.
5. Run `make check` with the normal repository test services configured.
6. Run `uv run python scripts/engineering_state.py check --base-ref origin/main --head-ref HEAD`.
7. Run `git diff --check origin/main...HEAD`; report exact commands, exit codes, environment, and SHA.

No ready PR or merge before applicable preflight passes. A failing assertion requires a scoped
correction; unavailable infrastructure remains QUALIFICATION_REQUIRED. The next implementation
owner consumes this design without treating it as evidence that agents, learning, or Forge exist.
