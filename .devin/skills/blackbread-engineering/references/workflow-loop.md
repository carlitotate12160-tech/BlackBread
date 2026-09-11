# Role-Separated Engineering Loop

Use this loop for every release-bearing BlackBread slice. It prevents a coding IDE from becoming the
architect, implementer, environment operator, reviewer, and release authority in one expensive run.

## State flow

```text
BASELINE_VERIFIED -> DESIGN_SEALED -> IMPLEMENTING -> LOCAL_GREEN
-> QUALIFIED -> PR_READY -> REVIEWED -> MERGEABLE
                           REVIEWED -> CORRECTION_REQUIRED
                           -> IMPLEMENTING -> LOCAL_GREEN -> QUALIFIED -> PR_READY -> REVIEWED
```

Terminal stop states are `DESIGN_HOLD`, `SPLIT_REQUIRED`, and `NOT_MERGEABLE`. A stopped state needs
new owner direction or new evidence; it must not trigger an automatic retry.

## Ownership

| Role | Reads | Emits | Must not do |
| --- | --- | --- | --- |
| Design controller | live baseline, relevant authority and code | design seal, implementation packet | write production code or hide unresolved feasibility |
| Implementation owner | `AGENTS.md`, live drift checks, design seal, implementation packet, allowed code/tests | RED/GREEN change, local preflight, ready branch/PR or qualification request | redo accepted architecture, expand files, review itself into mergeability |
| Qualification runner | exact commit and qualification runbook | environment-bound proof record | redesign, edit, commit, push, or substitute a different commit |
| Review/seal owner | exact PR diff, relevant invariants, checks, reviewer output | finding dispositions, correction packet, final seal | silently patch or sample reviewers repeatedly |
| Repository owner | final exact-head seal | squash-merge decision | bypass required gates |

One person or model may perform several roles sequentially, but each role starts from the previous
role's artifact and respects its write boundary.

## Read-once source snapshot

The design seal lists every authority source actually used as `path@blob_sha` and records the exact
decision extracted from it. Do not paste whole documents into downstream packets.

Each role still performs the live checks required by `AGENTS.md`. During one role run, do not re-read
an unchanged authority or repeat the same repository-wide search. Re-open only when:

- protected base, PR head, or recorded blob SHA changes;
- a required field in the seal or packet is missing;
- observed implementation contradicts the sealed decision;
- a proof fails for the intended invariant; or
- a STOP/SPLIT condition names the minimum source needed to decide it.

Record the changed fact and resume from the earliest invalid state. Do not restart the entire loop.

## Automation boundary

Automate deterministic collection and verification: Git SHAs and blob IDs, open PRs, changed files,
required checks, test execution, coverage and size budgets, safety-path classification, and unresolved
threads. Existing repository scripts and CI remain the authority for those checks.

Keep these decisions explicit and non-automatic:

- `ACCEPT`, `ACCEPT WITH CHANGES`, `REJECT`, and `DESIGN_SEALED`;
- whether a finding is reproduced, stale, false positive, or a design failure;
- any scope or authority expansion;
- any target-facing risk acceptance; and
- the final merge action.

Pilot the split packets on `M1.4c2b1`. Add orchestration software only after the pilot exposes a
repeated deterministic step that existing scripts or CI do not already own.
