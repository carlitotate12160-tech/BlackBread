# Correction Packet Template

The review/seal owner emits this once, after reviewing one exact PR head. It is a bounded delta, not
a replacement implementation prompt.

```text
STATE: CORRECTION_REQUIRED
SLICE:
PR:
REVIEWED_HEAD:
CORRECTION_OWNER:
DESIGN_SEAL_ID:
CLASSIFICATION: CODE_DEFECT | DESIGN_FAILURE
```

Use `CODE_DEFECT` only when the sealed design remains valid. `DESIGN_FAILURE` must name a violated
invariant and reachable counterexample and returns control to the design controller.

## Reproduced findings

| ID | Severity | Evidence/reproduction | Required behavior | Disposition |
| --- | --- | --- | --- | --- |
| `<id>` | blocker/hardening | `<command, test, or exact path>` | `<falsifiable result>` | fix/defer/reject with authority |

Do not include stale, duplicate, stylistic, speculative, or unreproduced reviewer suggestions.

## Bounded correction

```text
Allowed files:
Forbidden files: every unlisted file
Required regression RED:
Required GREEN and affected suites:
Unchanged public contracts and invariants:
Remaining correction budget:
Authoritative qualification to repeat:
```

## Return

```text
STATE: CORRECTED | STOPPED
OLD_HEAD:
NEW_HEAD:
CHANGED_FILES:
REGRESSION_EVIDENCE:
GREEN_EVIDENCE:
PREFLIGHT_AND_QUALIFICATION:
DIFF_SELF_REVIEW:
EXACT_NEXT_ACTION: final current-head review
```

One packet permits one cohesive correction. New findings after the correction cause `NOT_MERGEABLE`
or a new owner-selected slice; do not start an open-ended repair loop.
