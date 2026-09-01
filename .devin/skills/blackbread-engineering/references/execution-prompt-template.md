# Execution Prompt Template

The fill-in form of the *Execution prompt contract* (`execution-contract.md` §1) and the
*Required slice contract* (`architecture-planning.md`). It restates no rationale — it is the
skeleton to fill. Copy it, replace every `<...>`, delete the parenthetical guidance, and state each
rule once in its owning section (no rule repeated across sections). One slice per prompt.

---

Use the `blackbread-engineering` skill in `<IMPLEMENT | FIX | REVIEW>` mode.

# <Milestone>.<slice-id> — <one-sentence outcome>

## 1. Outcome and scope
- SLICE: `M<n>.<id>` — <what this slice makes true, one sentence>.
- MODE: `<IMPLEMENT | FIX | REVIEW>`. One bounded slice; you are the sole implementation owner of the
  branch. Do not re-plan or rescope already-accepted architecture; do not ask another agent to edit
  the branch.

## 2. Baseline (verify live; the checkpoint below is for drift detection only)
- protected base: `<sha>`   PR head: `<sha or n/a>`   branch: `<name>`
- Read completely: `AGENTS.md`, `.github/agent-delivery.json`, `ENGINEERING-STATE.md`, and only the
  implementation/test files this slice requires.
- If live base, head, diff, authority, open gaps, or blocker set differs materially from the
  checkpoint: `STOP/SPLIT` without editing and report the drift.

## 3. File map (the only files that may change)
| File | Action | Responsibility | Expected size |
| ---- | ------ | -------------- | ------------- |
| `<path>` | `<add | modify>` | `<one responsibility>` | `<small | medium>` |
| `tests/<path>` | `modify` | `<proof it carries>` | `<small>` |

All other files are forbidden. If a change outside this map appears necessary, `STOP/SPLIT` and
report the violated assumption — do not implement it.

## 4. Requirement / capability context
- REQ/CAP IDs touched: `<ENG-/REC-/STR-/CAP-/... + capability-registry IDs>` — state each one's
  current state (`DECIDED | IMPLEMENTED | VERIFIED | RELEASED`).
- Why, and what it connects to: <one short paragraph>. Moat = composition + proof, not API-wrapping.
  Candidate != authorization — every destination still passes the deterministic gate downstream.

## 5. Invariants and non-goals (stated once, here)
- Preserve: <deterministic safety = pure code, LLM emits typed proposals only; atomic transaction;
  lock/serialization point; tenant and engagement isolation; RLS fail-closed; immutable
  provenance/lineage; sealed preimages, migrations, golden vectors, versions; open-gap honesty>.
- Do NOT: <change production code or schema unless this slice is that change; introduce a new trust
  boundary; scope beyond this slice; rename public or private runtime symbols; move policy into
  tests/migrations/config to dodge budgets; density-game (compress, strip docs, single-letter
  names, merge responsibilities); open a second PR; force-push or rewrite history; call CodeRabbit,
  Sourcery, Codex, or any advisory bot manually; merge>.

## 6. Proof obligations (RED first; one oracle per claim)
For each behavior being added or corrected:

### <claim / defect name> — `<test name>`
- Passes only if: <exact positive conditions, one per line>.
- Must NOT pass because: <a broad `Exception`; a `sleep`/timing-luck; a tautological count; RLS
  concealing invalid data from the observer; an unrelated failure>.
- RED evidence: introduce a temporary, non-committed mutation or seam that removes the property,
  show the strengthened test fails, then restore the real implementation before GREEN.

### Wiring proof (non-island) — `<test name>`
- Drive the real Conductor autonomous path (not a fixture or a `live_fire` runner) and assert the
  new capability's output actually reaches its downstream consumer. Register the wiring transition in
  the wiring-debt gate if the repository tracks one.

## 7. Budget (single source)
- Caps come from `config/quality-budgets.json` (module <= 400, function <= 50, McCabe <= 10) and the
  protected-base allowance; do not restate numbers, do not raise a cap.
- Predict the runtime line/file delta with review margin. Budget is an architecture signal, not a
  formatting target — if honest code will not fit, `STOP/SPLIT`, do not compress.

## 8. STOP/SPLIT conditions (the single list; other sections reference this)
Stop without broadening the diff and report exact evidence when: <live base/head drift; a further
implementation responsibility becomes necessary; production behavior or a sealed migration must
change; the proof needs a new runtime seam; a real-PostgreSQL proof is unavailable; an authority
conflict appears; a module cannot stay in budget without compression; a new correctness-invariant
class appears>.

## 9. Local preflight (ordered; opening the PR before this is green is a task failure)
1. focused RED or temporary-mutation proof;
2. focused corrected/added tests GREEN;
3. affected compatibility suites (e.g. ledger, tenancy);
4. real PostgreSQL for migration/transaction/lock/RLS/replay claims;
5. `uv sync --locked --all-groups`;
6. `make check`;
7. size / diff / governance checks;
8. `git diff --check`;
9. inspect the complete diff against protected `main`.

Oracle ARM64 only (`.venv312/bin/python3 -m pytest` or `make check`); never bare `pytest`. `git pull`
and re-verify first.

## 10. Delivery
- One conventional commit; normal fast-forward push to the existing branch; no force-push; no new PR;
  no manual advisory-bot call; let configured CI and the binding PR-Agent/DeepSeek review run; do not
  merge.
- Inspect every thread against the exact new head. Fix a reproduced valid finding; for a stale or
  false-positive finding, reply with exact-head evidence and resolve its thread with that note.
  Dispositioning advisory findings is a practice that satisfies thread resolution, not a blocking
  gate; only a reproduced valid correctness/security finding blocks. Resolve a thread only after its
  evidence exists.

## 11. Required return
verified base before editing; old head; new head; complete changed-file list; RED/mutation evidence;
focused GREEN evidence; real-PostgreSQL evidence; full `make check`, coverage, and safety-coverage
results; quality and diff-budget results; disposition for every previously unresolved thread; current
CI status; current binding PR-Agent exact-head review status; unresolved threads remaining; open gaps;
claims explicitly not made; `MERGEABLE` or `NOT MERGEABLE`; exactly one next action. Do not merge.
