# Design Seal Template

The design controller fills this once after architecture feasibility passes. It is the source for the
implementation packet; it is not an implementation prompt.

```text
STATE: DESIGN_SEALED
DESIGN_SEAL_ID: <slice>@<protected-base-sha>
SLICE:
SEALED_AT_UTC:
PROTECTED_BASE_SHA:
SELECTED_NEXT_SLICE:
DESIGN_CONTROLLER:
APPLICABLE_LENSES:
```

## Source manifest

List only sources actually used. Record repository files as `path@blob_sha` and live facts with their
retrieval time. Add a one-sentence extracted decision; do not paste the document.

| Source | Exact version | Decision used |
| --- | --- | --- |
| `AGENTS.md` | `<blob SHA>` | `<decision>` |
| `<relevant authority>` | `<blob SHA or live identifier>` | `<decision>` |

## Feasibility result

```text
EXACT FALSIFIABLE CLAIM:
SMALLEST VIOLATING COUNTEREXAMPLE:
COMPONENT AUTHORITY:
INFORMATION SUFFICIENCY: PASS — <evidence>
ADVERSARIAL COUNTEREXAMPLE: PASS — <evidence>
PRODUCER/CONSUMER CONTINUITY: PASS — <evidence>
BOUNDARY ELIMINATION: PASS — <evidence>
INTERMEDIATE SAFETY: PASS — <evidence>
FUTURE-CONSUMER SAFETY: PASS — <evidence>
PROOF ORACLES: PASS — <evidence>
ARCHITECTURE DECISION: ACCEPT | ACCEPT WITH CHANGES
```

Any bare `PASS`, missing evidence, or applicable `FAIL` produces `DESIGN_HOLD`, not a seal.

## Sealed boundary

```text
Outcome:
Public contract:
Inputs:
Outputs:
Failure modes:
Durable state owner:
Ephemeral state owner:
Trust boundaries crossed:
Intermediate reachability:
Named next consumer:
Claims explicitly not made:
Non-goals:
```

## Execution derivation

```text
Allowed production responsibilities:
Required proof categories and oracles:
Integration environments:
Budget source and reserved correction margin:
Mandatory STOP/SPLIT conditions:
```

If any downstream packet needs a new authority source, public contract, trust boundary, or proof
category, invalidate this seal and return to the design controller.
