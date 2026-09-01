# Architecture Planning

Use this reference for new milestones, slice selection, design revisions, implementation prompts, and architecture disputes.

## Preflight decision

Lead with exactly one decision:

- `ACCEPT`
- `ACCEPT WITH CHANGES`
- `REJECT`

Support it with live repository evidence, applicable authority, current code and schema behavior, test evidence, trust boundaries, and budget estimates. Separate proven facts from proposed design.

## Derive the slice

1. Restate the user-visible or engineering outcome.
2. Identify prerequisites and blocking gaps.
3. Map the dependency order and trust boundaries.
4. Find the smallest independently sealable vertical slice.
5. Prove that its intermediate state is unreachable, fail-closed, or independently safe.
6. Estimate runtime changed lines, runtime files, production-module size, migrations, and test-module size with review margin.
7. Split proactively when one change crosses independently sealable trust boundaries or is unlikely to fit honestly under repository limits.

Never split into an intermediate state that exposes unsafe authority, false provenance, partial publication, or target effects. Conversely, do not keep unrelated work together merely because it shares a milestone label.

## Required slice contract

An implementation-ready plan or prompt must contain:

- verified protected-main baseline and branch;
- completed prerequisites and current gaps;
- exact scope and named production responsibilities;
- public and private boundary contracts;
- durable versus ephemeral state ownership;
- migration and rollback semantics where applicable;
- tenant, provenance, concurrency, cancellation, and failure invariants;
- explicit non-goals and intermediate reachability;
- strict RED-to-GREEN sequence and negative cases;
- real integration environment requirements;
- runtime, file, module, function, complexity, test-size, and coverage budgets;
- documentation and gap-state updates;
- seal criteria, reviewer policy from live authority, and STOP/SPLIT conditions;
- next slice without inventing a future main SHA.

## Finish planning

Do not cycle through cosmetic plan revisions. After all correctness, safety, boundary, evidence, and budget blockers are resolved, declare the plan implementation-ready. Further architecture review requires new live drift, failed proof, reproduced defect, or a stated STOP/SPLIT condition.

