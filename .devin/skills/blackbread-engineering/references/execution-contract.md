# Execution and seal contract

These contracts tighten the preflight, execution, and review rules for every
BlackBread slice and are not waived by urgency, owner pressure, or a milestone
deadline. They apply to every operating mode of the `blackbread-engineering`
skill.

1. **Execution prompt contract.** Before any code or test is written, the active
   execution prompt or plan must name:
   - the **allowed files** for this slice and the **forbidden files** that must
     not be touched;
   - the **proof obligations** (safety, correctness, provenance, concurrency,
     tenant isolation, and rollback claims that must be proven, plus the oracle
     for each);
   - a **predicted budget with review margin** — runtime lines, runtime files,
     production-module lines, function lines, McCabe complexity, and test-module
     lines, with explicit headroom so the final diff fits under the protected
     caps;
   - explicit **STOP/SPLIT conditions** that end work if the slice crosses a
     trust boundary, requires a protected-migration rewrite, no longer fits the
     predicted budget, or exposes a reachable unsafe or semantically invalid
     intermediate state.

2. **Preflight-before-PR contract.** Opening a pull request before the full
   local preflight is green is a task failure. The local preflight is green only
   when: focused RED-to-GREEN tests pass, the affected suite passes,
   `make check` passes, size and coverage budgets pass, the complete diff has
   been inspected for scope expansion and control weakening, and the live GitHub
   state still matches the selected slice. A PR is not a CI sandbox.

3. **Adversarial-review contract.** A slice gets at most one adversarial
   review cycle and at most one cohesive correction cycle. After that, the
   current head is either sealed (all gates green and all evidence bound to
   the exact head) or rejected (blockers remain, the slice must be split, or
   trust boundaries are unclear).

   Use the binding reviewer and trigger mechanism required by live repository
   authority; never cache a provider, model, bot name, or trigger method in
   this contract. Allow configured automation to run once, or use only the
   explicitly approved trigger when automation is unavailable. Do not poll,
   re-trigger, or loop advisory reviewers to obtain a cleaner response.

   Advisory findings must be reproduced and dispositioned. A reproduced valid
   correctness or security finding blocks the seal. A stale, duplicate, or
   false-positive finding requires exact-head evidence before its thread is
   resolved. The binding independent review for a safety-critical path cannot
   be waived by advisory output or owner disposition alone.

4. **Density-gaming contract.** Do not compress statements, delete comments or
   documentation, merge unrelated responsibilities into one module or function,
   rename variables to single letters, or use any other line-budget gaming to fit
   the diff under a cap. If the honest implementation does not fit the predicted
   budget, STOP and split the slice; do not shrink the code. The budget is an
   architecture signal, not a target.
