# Implementation and Delivery

Use this reference only after implementation has been authorized.

## Work ownership

- Verify the exact base again immediately before branching.
- Preserve unrelated tracked and untracked user work.
- Use one implementation owner for the feature branch.
- Do not broaden authorization from review or planning into external mutations unless the user requested implementation or delivery.

## Strict TDD

1. Add the smallest focused test that fails for the intended reason.
2. Capture RED evidence before production code.
3. Implement the minimum coherent boundary.
4. Run the focused GREEN test and affected compatibility suites.
5. Run real PostgreSQL for migrations, transactions, locks, RLS, cancellation, replay, or persistence claims.
6. Run repository synchronization, lock validation, full gates, safety coverage, and budgets required by the live repository.
7. Inspect the complete diff against protected main.

Concurrency proof must force interleavings with barriers or events. Sleeps and lucky scheduling are not proof. Test exceptions, cancellation, rollback, cleanup, wrong tenant, malformed input, stale state, and fail-closed behavior.

## Code boundaries

- Keep pure domain validation separate from persistence and orchestration.
- Keep public entry points thin and state ownership explicit.
- Avoid generic manager, service, helper, or utils modules.
- Treat module and function size warnings as architecture signals, not formatting problems.
- Do not move policy into tests, migrations, generated files, or configuration to evade runtime budgets.
- Never change a sealed preimage, migration, golden vector, version, or compatibility contract unless the accepted slice explicitly requires it.

## Delivery

Before push, confirm the complete diff contains no scope expansion, secrets, generated noise, weakened controls, or false status claims.

Use a feature branch, conventional commit, normal fast-forward push, and pull request. Never push directly to main or rewrite history. Bind all evidence to the exact current PR head.

Inspect every surfaced AI or bot comment. Reproduce findings before fixing them; fix valid findings minimally and disposition stale or false-positive findings with evidence. Use the reviewer and required-check policy from live repository authority rather than a cached model name or remembered workflow.

Do not merge while required CI, binding review, branch currency, valid threads, changes-requested reviews, blocking gaps, or budgets remain unresolved. Respect a user instruction to stop before merge.

## Stop conditions

Stop and report exact evidence when implementation requires a new trust boundary, unsafe intermediate state, authority expansion, unrelated refactor, budget relaxation, protected migration rewrite, unavailable real integration proof, destructive action outside scope, or permission not already granted.

