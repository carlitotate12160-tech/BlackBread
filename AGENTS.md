# BlackBread Agent Instructions

BlackBread is an authorized, covert, agentless external red-team / adversary-emulation platform.
This file is the session entry point: how to start, where authority lives, and which file owns each
rule. It deliberately does not restate the rules — it points to their single source, so the same
rule is never maintained in two places. Full architecture and safety decisions: `ADR-FINAL-002.md`
and `PRD.md`.

## Start from live truth

Before planning, editing, reviewing, or delivering:

1. Read this `AGENTS.md`, then `ENGINEERING-STATE.md` (the owner's currently selected slice).
2. Verify live GitHub independently — protected `main` SHA, open PRs and exact heads, CI, reviews,
   unresolved and pending AI-review threads, rulesets, required checks, and active P0/P1 gaps.
3. Compare the `ENGINEERING-STATE.md` checkpoint with live GitHub; if they differ, reconstruct the
   drift and report it before editing. Do not silently continue from either version.
4. Read only the authority and implementation files the selected slice requires.
5. Check the working tree; preserve unrelated tracked and untracked changes. Report the verified
   baseline before editing.

Conversation memory, session summaries, copied prompts, and handoff prose are never implementation
authority. A state document cannot prove a feature, gap, milestone, or release is complete — only
tests, migrations, runtime behavior, and release evidence do.

## Authority order

Lower authority may strengthen but never weaken higher authority. If two authorities, or live GitHub
rules, contradict each other, stop and report the contradiction; do not choose the easier rule.

1. law, signed SOW, and engagement manifest;
2. accepted ADR decisions in `ADR-FINAL-002.md` and `ADR-FINAL-003.md`;
3. `PRD.md`;
4. `.devin/rules/blackbread.md` — the always-on hard invariants and engineering guardrails;
5. `GAP-REGISTER.md` — blocker status and closure evidence;
6. `config/capability-registry.json` and schemas — the only tool/capability allowlist;
7. repository skills, including `.devin/skills/build-blackbread-agent/SKILL.md`;
8. tests, readmes, derived summaries, and history.

Load `.github/agent-delivery.json` before any branch, push, pull request, or merge operation.

## Where each rule is owned (follow the source; do not restate it here)

- Security invariants, capability and tool rules, prompt-injection defense, tooling, size caps, and
  honesty: `.devin/rules/blackbread.md`.
- Hard delivery gates (branch protection, required checks, review and thread-resolution policy):
  `.github/agent-delivery.json` (machine contract) and `.github/BRANCH-PROTECTION.md`.
- How to plan, slice, implement, review, seal, and hand off — including the execution-prompt,
  preflight-before-PR, STOP/SPLIT, adversarial-review, and density-gaming contracts: the
  `blackbread-engineering` skill and its `references/`.
- Numeric quality caps (module, function, complexity, coverage): `config/quality-budgets.json` and
  `pyproject.toml` are the single binding source. Prose never redefines these numbers.

## Session discipline (entry-point rules this file owns)

- At most one implementation slice is active. One agent owns writes to its branch; a second agent
  may perform read-only adversarial review only. Serialize overlapping writes; parallelize only
  independent read-only exploration.
- Use `DECIDED`, `IMPLEMENTED`, `VERIFIED`, and `RELEASED` only with the evidence repository
  authority requires. Never claim a milestone, release, or gap closed from prose, unit tests, or a
  partial path. Record blocking work in `GAP-REGISTER.md`; never hide it as a TODO, skipped test,
  dormant path, optional check, or undocumented waiver.
- Implement one smallest safety-complete vertical slice per pull request. Do not mix unrelated
  governance, infrastructure, refactoring, and feature work, or pull future components into a slice
  the current contract does not require.
- An explicit new repository-owner instruction may replace the selected next slice, but may not
  weaken law, authorization, accepted architecture, safety invariants, required delivery gates, or
  blocking-gap honesty. Record the replacement in `ENGINEERING-STATE.md` so later sessions do not
  depend on conversational memory.
- Every implementation handoff and pull-request body states: verified protected-`main` SHA; exact
  current PR head; bounded scope and non-goals; RED and GREEN evidence; tests and repository gates
  run; current CI, reviews, AI/bot-comment dispositions, and unresolved threads; open gaps and
  claims explicitly not made; blockers; and the next owner-selected slice.
