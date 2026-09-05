# Execution Prompt Template

This is the fill-in form for the *Execution prompt contract*
(`execution-contract.md` §1) and the *Required slice contract*
(`architecture-planning.md`).

Use it only after the architecture decision is `ACCEPT` or
`ACCEPT WITH CHANGES` and the slice is implementation-ready.

Copy the template, replace every `<...>`, remove all unused guidance and
inapplicable alternatives, and state each rule only in its owning section.
One prompt owns exactly one slice.

---

Use the `blackbread-engineering` skill in `<IMPLEMENT | FIX | REVIEW>` mode.

# <Milestone>.<slice-id> — <one-sentence verifiable outcome>

## 1. Outcome and scope

* SLICE: `<M<n>.<id>>` — <one sentence describing what becomes verifiably true>.
* MODE: `<IMPLEMENT | FIX | REVIEW>`.
* DELIVERY PATH: `<NEW_SLICE | EXISTING_PR | READ_ONLY_REVIEW>`.
* ARCHITECTURE DECISION: `<ACCEPT | ACCEPT WITH CHANGES>` — <accepted decision and material conditions>.
* IMPLEMENTATION OWNER: `<one owner>`.

For `IMPLEMENT` or `FIX`, one owner controls all writes to the branch. Do not
delegate overlapping edits or re-plan accepted architecture unless live drift,
a failed invariant, an unsafe intermediate state, or a STOP/SPLIT condition
requires reopening the design.

Required boundary:

```text
Public contract:
Inputs:
Outputs:
Failure modes:
State owner:
Trust boundary:
```

Intermediate reachability: <explain why the incomplete slice is unreachable,
fail-closed, non-executable, or independently safe>.

## 2. Baseline (verify live; this checkpoint is drift detection only)

```text
repository: <owner/repository>
protected base: <full SHA>
branch: <branch name or n/a>
PR number: <number or n/a>
PR head: <full SHA or n/a>
known checkpoint drift: <exact drift or none>
```

Before editing or issuing a review verdict:

1. read `AGENTS.md` completely;
2. load `.github/agent-delivery.json`;
3. verify protected main, open PRs, exact heads, checks, reviews, pending or
   unresolved review threads, active rulesets, required checks, and bypass
   actors;
4. compare `ENGINEERING-STATE.md` with live GitHub;
5. read the relevant accepted ADR, PRD, gap, capability-registry,
   implementation, migration, and test authorities;
6. inspect the working tree and preserve unrelated changes.

If the live base, PR head, diff, authority, required checks, reviewer policy,
open gaps, or blocker set differs materially from the checkpoint, invoke
Section 8 without editing.

## 3. File map (the only files that may change)

| File           | Action | One responsibility | Contract impact |          Predicted delta |        Expected final size |           |           |
| -------------- | ------ | ------------------ | --------------- | -----------------------: | -------------------------: | --------- | --------- |
| `<path>`       | `<add  | modify             | delete>`        |       `<responsibility>` | `<none or exact contract>` | `<lines>` | `<lines>` |
| `tests/<path>` | `<add  | modify             | delete>`        | `<proof responsibility>` |                `test only` | `<lines>` | `<lines>` |

Explicitly forbidden files:

```text
<paths or path groups that must not change>
```

Every file not listed in the allowed map is forbidden. If another file becomes
necessary, invoke Section 8 instead of silently expanding the diff.

For `READ_ONLY_REVIEW`, state `no files may change`.

## 4. Requirement, dependency, and capability context

| ID                 | Current state | Effect of this slice | Evidence required |          |      |          |                  |                      |
| ------------------ | ------------- | -------------------- | ----------------- | -------- | ---- | -------- | ---------------- | -------------------- |
| `<REQ/CAP/GAP ID>` | `<DECIDED     | IMPLEMENTED          | VERIFIED          | RELEASED | OPEN | CLOSED>` | `<exact effect>` | `<oracle or source>` |

Completed prerequisites:

```text
<released prerequisites with live evidence>
```

Active gaps and blockers:

```text
<gap, severity, what it blocks, and whether it blocks this slice>
```

Dependency order:

```text
<prior slice> -> <this slice> -> <next slice>
```

Explain briefly why the slice exists and how it connects to the larger system.

If the slice handles agent reasoning, campaign state, graph reachability,
capability selection, or model output, state explicitly that these may produce
typed candidates only. They cannot authorize execution, change scope, override
policy or OPSEC, issue leases or work orders, or promote unverified facts.

When campaign or world-snapshot boundaries are relevant, read
`ADR-FINAL-003.md` and preserve its separation of reasoning, coordination,
evidence, and execution authority.

## 5. Invariants, ownership, compatibility, and non-goals

### Invariants

* Authority separation: <which deterministic component owns each decision>.
* Tenant and engagement isolation: <required binding and negative behavior>.
* Provenance and integrity: <digests, lineage, versions, sealed preimages, or
  immutable evidence that must remain bound>.
* State ownership:

  * durable state: <owner or none>;
  * ephemeral state: <owner or none>;
  * caller-supplied facts: <owner or none>.
* Concurrency and TOCTOU: <serialization point, snapshot rule, lock, revision,
  validity interval, or explicit N/A>.
* Cancellation and rollback: <required behavior or explicit N/A with reason>.
* Compatibility: <contracts, migrations, versions, symbols, and golden vectors
  that remain unchanged>.
* Fail-closed behavior: <exact behavior when facts are missing, stale,
  contradictory, malformed, or unavailable>.
* Reachability: <what can and cannot reach production or execution after this
  slice>.

### Non-goals

```text
<exact responsibilities deferred to later slices>
<authority this slice does not gain>
<claims this slice does not make>
```

Do not introduce a new trust boundary, move policy into tests/configuration,
modify a sealed preimage or migration, rename an established contract, or
expand execution authority unless that change is explicitly authorized in
Sections 1–4.

## 6. Proof obligations (RED first; one oracle per claim)

List every safety, correctness, provenance, tenant-isolation, concurrency,
TOCTOU, cancellation, rollback, and reachability claim. Mark a category `N/A`
only with a concrete architectural reason.

### `<claim or defect>` — `<test or other oracle>`

Passes only if:

```text
<exact positive condition>
<exact boundary condition>
<exact negative/failure condition>
```

Must not pass because of:

```text
broad exception handling
sleep or scheduler luck
mocking the system under test
a tautological assertion or count
an unrelated validation failure
RLS or filtering hiding invalid durable state from the observer
```

RED method:

```text
<new behavior: focused test fails because the behavior is absent>
<defect: regression test reproduces the defect on the unmodified implementation>
<sealed/high-risk invariant: temporary non-committed mutation removes the property and the oracle fails>
```

Use temporary mutation proof only when ordinary RED evidence does not
demonstrate that the oracle is sensitive to the claimed invariant. Restore the
real implementation before GREEN and never commit the mutation.

GREEN evidence:

```text
<focused command and expected result>
```

### Wiring or intentional non-wiring proof — `<test name>`

Select exactly one:

**POSITIVE_WIRING**

* Drive the real production path rather than a fixture-only, test-only,
  demonstration, or `live_fire` path.
* Prove the new output reaches the named downstream consumer.
* Register or close wiring debt only with actual reachability evidence.

**INTENTIONAL_NON_WIRING**

* Prove no production entry point imports or invokes the new component.
* Prove its outputs cannot represent execution authority or target effects.
* Name the later slice that owns positive wiring.
* Do not claim end-to-end behavior.

For concurrency claims, force the relevant interleaving with barriers, events,
transaction isolation, or another deterministic synchronization oracle. Sleeps
and repeated lucky execution are not concurrency proof.

## 7. Budget (single source, with review margin)

Read numeric limits from the live `config/quality-budgets.json`,
`pyproject.toml`, and protected-base budget authority. Do not copy numeric caps
into this reusable template and do not change a cap to fit a slice.

| Metric                             | Protected-base value | Predicted change/final value | Reserved review margin |
| ---------------------------------- | -------------------: | ---------------------------: | ---------------------: |
| Runtime changed lines              |            `<value>` |                    `<value>` |              `<value>` |
| Runtime changed files              |            `<value>` |                    `<value>` |              `<value>` |
| Largest affected production module |            `<value>` |                    `<value>` |              `<value>` |
| Largest affected function          |            `<value>` |                    `<value>` |              `<value>` |
| Maximum affected McCabe complexity |            `<value>` |                    `<value>` |              `<value>` |
| Largest affected test module       |            `<value>` |                    `<value>` |              `<value>` |
| Migration count/size               |     `<value or n/a>` |             `<value or n/a>` |       `<value or n/a>` |

Budget is an architecture signal, not a code-formatting target. Do not compress
statements, merge unrelated responsibilities, remove meaningful comments or
docstrings, shorten names unnaturally, hide logic in configuration/tests, or
perform another density-gaming technique. If clear and honest code cannot fit
with review margin, invoke Section 8 and split the slice.

## 8. STOP/SPLIT conditions (single authoritative list)

Stop without broadening the diff, opening a PR, or making unsupported claims
when any of the following occurs:

* live base, head, diff, ruleset, required-check, reviewer, authority, gap, or
  blocker drift invalidates the accepted slice;
* another implementation responsibility or trust boundary becomes necessary;
* an intermediate state becomes reachable, executable, partially published,
  falsely authoritative, or otherwise unsafe;
* a public compatibility contract, sealed preimage, protected migration, or
  golden vector must change without explicit authorization;
* the proof requires a new runtime seam, persistence mechanism, transaction,
  lock, capability, or external system not declared in the slice;
* the authoritative integration environment required for a claim is
  unavailable;
* concurrency, rollback, cancellation, tenant isolation, or provenance cannot
  be proven deterministically;
* the implementation no longer fits its predicted budget with review margin;
* satisfying the budget would require density gaming;
* a new correctness or security invariant class appears;
* repository instructions or higher authority conflict.

Return the exact evidence, the violated assumption, whether the slice should be
rejected or split, and the smallest safe follow-up. Do not implement the
expanded scope.

## 9. Local preflight (ordered; PR creation or update waits for GREEN)

1. verify the base/head again and synchronize using the repository-approved
   non-destructive workflow;
2. capture focused RED or regression evidence;
3. capture temporary-mutation evidence where Section 6 requires it;
4. run focused corrected or added tests GREEN;
5. run affected compatibility, negative, tenancy, and boundary suites;
6. run real integration proofs required by the claims;
7. run the repository dependency/lock synchronization command;
8. run the complete repository check command;
9. run size, diff, coverage, safety-coverage, migration, and governance checks;
10. run `git diff --check`;
11. inspect the complete diff against the verified protected base for scope
    expansion, control weakening, secrets, generated noise, and false status
    claims;
12. re-verify live GitHub before delivery.

Integration applicability:

```text
PostgreSQL: <REQUIRED with exact suites | N/A with reason>
Oracle ARM64/platform qualification: <REQUIRED with exact commands | N/A with reason>
Other external system: <REQUIRED with exact proof | N/A with reason>
```

Use the authoritative interpreter, environment, and commands from the live
repository. Do not substitute cached platform names or commands. Do not make an
integration claim when its authoritative environment was unavailable.

Opening or updating a PR before applicable local preflight is green is a task
failure. A PR is not a CI sandbox.

## 10. Delivery and exact-head review

Follow the selected `DELIVERY PATH`.

### `NEW_SLICE`

* Create exactly one feature branch from the verified protected base.
* Make the bounded conventional commit or commit sequence permitted by the
  execution contract.
* Push normally and open exactly one ready PR only after Section 9 is green.

### `EXISTING_PR`

* Verify the existing branch and exact PR head before editing.
* Commit the cohesive correction and push normally to the same branch.
* Do not create another PR.

### `READ_ONLY_REVIEW`

* Do not create or modify a branch, commit, push, PR, comment, review, label, or
  thread unless the user separately authorizes that mutation.

For mutating delivery paths:

* never push directly to protected main, force-push, rewrite history, or merge;
* use the reviewer classification and binding-review policy from current live
  repository authority rather than a cached bot, provider, or model name;
* allow configured review automation to run once, or use only the explicitly
  approved trigger when required;
* perform at most one adversarial-review cycle and one cohesive correction
  cycle;
* after any correction, bind CI, review, thread, and test evidence to the new
  exact head.

Inspect every surfaced finding. Reproduce it before changing code. Fix a valid
finding minimally. For a stale, duplicate, or false-positive finding, provide
exact-head evidence before resolving its thread. An advisory opinion alone does
not override reproduced code behavior, but a reproduced correctness or
security defect blocks the seal.

## 11. Required return and seal

Return:

```text
verified protected base
delivery path
branch and PR number
old exact head
new exact head
complete changed-file list
public-contract changes
RED/regression evidence
temporary-mutation evidence or justified N/A
focused GREEN evidence
affected-suite evidence
PostgreSQL evidence or justified N/A
platform-qualification evidence or justified N/A
full repository-check result
coverage and safety-coverage results
quality and diff-budget results
complete-diff self-review result
current required-check status
current binding exact-head review status
all finding dispositions
unresolved or pending threads
active gaps and blockers
claims explicitly not made
remaining risks
MERGEABLE or NOT MERGEABLE
exactly one next action
```

A `MERGEABLE` verdict requires every applicable proof and live delivery gate to
be satisfied on the exact current head. Never infer release, milestone
completion, gap closure, production reachability, or execution authority from
a partial slice.
