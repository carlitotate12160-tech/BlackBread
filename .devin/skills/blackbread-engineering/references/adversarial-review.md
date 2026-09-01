# Adversarial Review and Seal

Use this reference for pull-request review, patch assessment, bot findings, post-merge audit, and mergeability decisions.

## Bind the review

- Verify protected base, exact current PR head, complete diff, CI, reviews, threads, and open gaps.
- Ignore stale PR-body head claims and superseded bot comments except as history.
- Review the live implementation and tests, not summaries or claimed evidence.

## Review dimensions

Examine:

- contract correctness and canonicalization;
- authorization, scope, target identity, capability, and OPSEC boundaries;
- tenant isolation, provenance, state-root, ledger, replay, and fail-closed behavior;
- database constraints, privileges, RLS, migration lifecycle, atomicity, locking, cancellation, and cleanup;
- concurrency interleavings and stale-state behavior;
- trust-boundary placement, module responsibilities, circular dependencies, complexity, and god-object risk;
- negative test completeness, real integration proof, coverage, budgets, and compatibility;
- documentation status, gap honesty, and claims not supported by release evidence.

When practical, reproduce suspected integrity gaps with a focused test, SQL transaction, malformed object, concurrency barrier, or deterministic example. Do not label a theoretical concern as a blocker without showing the violated invariant and reachable path.

## Finding disposition

Classify findings as:

- **Blocker:** reachable correctness, security, integrity, authorization, migration, atomicity, or delivery failure that must be fixed before merge.
- **Hardening:** bounded improvement justified in the current responsibility and budget.
- **Deferred:** valid work owned by a later slice with a safe current boundary and explicit gap.
- **False positive or stale:** contradicted by exact-head code, tests, schema, or authority.

Do not defer a false claim exposed by the current API merely because a later milestone could build a stronger system. Narrow or remove the unsupported claim now.

## Mergeability output

The binding independent review for safety-critical paths is mandatory and cannot
be waived by advisory bots or owner disposition alone. Final seal follows the
repository owner, but only after the binding review is complete or dispositioned
with evidence.

Lead with `MERGEABLE` or `NOT MERGEABLE`, then report:

- exact base and head;
- blocker and hardening findings with evidence;
- focused, integration, full-gate, coverage, and budget results;
- required reviewer and bot dispositions;
- unresolved threads or changes requests;
- open gaps and scope exclusions;
- confirmation that no future milestone or target-facing capability was smuggled into the diff.

