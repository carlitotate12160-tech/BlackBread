# Compact Implementation Packet Template

Use only after a matching `DESIGN_SEALED` record exists. The implementation owner verifies live drift
but does not repeat architecture. Replace every placeholder and remove unused rows. Keep the filled
packet compact; link `path@blob_sha` sources instead of copying ADRs, diffs, logs, or review policy.

```text
MODE: IMPLEMENT | FIX
SLICE:
DESIGN_SEAL_ID:
PROTECTED_BASE_SHA:
CORRECTION_PACKET_ID: <required when MODE: FIX>
REVIEWED_HEAD_SHA: <required when MODE: FIX>
BRANCH:
DELIVERY_PATH: NEW_SLICE | EXISTING_PR
IMPLEMENTATION_OWNER:
```

## Drift check

Read `AGENTS.md`, `.github/agent-delivery.json`, engineering state, and the sealed source manifest.
Verify live base/open-PR state and the working tree. Continue only when the base, selected slice,
ruleset, gaps, and all recorded source blobs still match. For `MODE: FIX`, also verify
`CORRECTION_PACKET_ID` and `REVIEWED_HEAD_SHA` match the emitted correction packet and its reviewed
PR head before any edit. Otherwise return `DESIGN_DRIFT` with the
single changed fact; do not re-plan inside the IDE.

## Outcome and boundaries

```text
Exact outcome:
Public contract change:
Named producer:
Named consumer:
Durable state owner:
Intermediate reachability:
Claims not made:
Non-goals:
```

## File contract

| Allowed file | Action | One responsibility | Predicted delta/final size |
| --- | --- | --- | --- |
| `<path>` | add/modify/delete | `<responsibility>` | `<values>` |

Every unlisted file is forbidden. A newly required file returns `SPLIT_REQUIRED`; do not expand the
table during implementation.

## Invariants

```text
Authority separation:
Tenant/engagement isolation:
Provenance/integrity:
Concurrency/TOCTOU:
Cancellation/rollback:
Compatibility/sealed artifacts:
Fail-closed behavior:
Execution or target-effect reachability:
```

Use `N/A — <architectural reason>` where a category truly does not apply.

## RED-to-GREEN proof

| Claim | RED/regression oracle | GREEN command | Negative control |
| --- | --- | --- | --- |
| `<falsifiable claim>` | `<test and intended failure>` | `<command>` | `<case>` |

Wiring mode: `POSITIVE_WIRING | INTENTIONAL_NON_WIRING`

```text
Production path or non-reachability proof:
Named downstream consumer or later owner:
Temporary mutation proof required: yes/no — <reason>
```

## Ordered work

1. Capture the focused RED or regression evidence.
2. Implement the minimum coherent change in allowed files only.
3. Run focused GREEN and affected negative/compatibility suites.
4. Inspect the complete diff for scope, authority, and status-claim drift.
5. Run the local preflight below.
6. Open/update one ready PR only when every applicable local proof is green.

## Budget and local preflight

Read numeric caps from live repository sources; never copy reusable cap values here or change a cap.

```text
Predicted runtime lines/files + correction margin:
Largest affected module/function/complexity:
Largest affected test module:
Migration count/size:
Focused tests:
Affected suites:
Real PostgreSQL:
Oracle/platform qualification:
Dependency/lock synchronization:
Full repository check:
Coverage, safety coverage, size and diff budgets:
git diff --check and complete-diff review:
```

If an applicable external proof cannot run locally, return `QUALIFICATION_REQUIRED` with a filled
qualification runbook. Do not open a ready PR or claim that proof.

## STOP/SPLIT

Stop without broadening the diff when live authority drifts; the design seal lacks a fact; another
trust boundary, public contract, file, migration, capability, or external system becomes necessary;
an intermediate state becomes reachable or falsely authoritative; a sealed artifact must change;
deterministic proof is impossible; the budget loses correction margin; or density gaming would be
required.

Return only the changed fact, violated assumption/invariant, evidence, and `DESIGN_DRIFT`,
`DESIGN_FAILURE`, or `SPLIT_REQUIRED`. Do not restart architecture yourself.

## Required implementation return

```text
STATE: LOCAL_GREEN | QUALIFICATION_REQUIRED | PR_READY | DESIGN_DRIFT | DESIGN_FAILURE | SPLIT_REQUIRED
BASE_SHA:
HEAD_SHA:
CHANGED_FILES:
RED_EVIDENCE:
GREEN_EVIDENCE:
LOCAL_PREFLIGHT:
QUALIFICATION_STATUS:
BUDGET_RESULT:
DIFF_SELF_REVIEW:
OPEN_GAPS_AND_CLAIMS_NOT_MADE:
PR_URL_OR_NEXT_ACTION:
```
