ADR-GOV-IP-PROVENANCE-001A — Source Provenance and Deterministic Admission
Status: ACCEPTED — 2026-09-21.
Slice: GOV-IP-PROVENANCE-001A (architecture/documentation only).
Implementation: NOT IMPLEMENTED by this document.
Owner: repository owner; architecture controller owns boundary design.
Next consumer: GOV-IP-PROVENANCE-001B read-only evaluator, then GOV-GRADER-001B.
Companion: ADR-GOV-GRADER-001A.md.
Decision boundary: engineering source admission; no target/runtime authority.
0. Context and verified baseline
BlackBread needs a bounded way to evaluate the declared origin and permitted engineering use of
IDE-authored changes. Green tests, a source hash, a license scanner, and a model's confidence answer
different questions. None alone establishes legal compatibility or ownership.
The design preserves ADR-FINAL-004 policy minimalism: this is an engineering control, not another
Policy Kernel rule, campaign approval, capability registry, or strategy gate.
Read-only GitHub verification on 2026-09-21, completed at 01:57 UTC:
Fact
Observation
Protected main
`c818bd045384a3cb6f467edfd723c3dd1a4e2ca5`
PR #106
merged; head `7439633208b2c119e2640eeb11a7000cedc395bd`
Open PRs
none at retrieval
Main checks
seven reported check runs succeeded, including ci-ok and both CodeQL Analyze jobs; no GitGuardian check returned on the squash SHA
PR #106 head checks
ten reported checks succeeded, including ci-ok, GitGuardian and CodeQL
PR #106 reviews/threads
returned reviews COMMENTED; one inline thread, resolved
Ruleset 21644438
active; strict currency; ci-ok and GitGuardian required; CodeQL high-or-higher/errors; squash; zero approvals; thread resolution; no bypass
Engineering state
revision 11; last released M1.4c2b1b; selected runtime slice M1.4d
Root license metadata
recursive tree contains no LICENSE/NOTICE file; pyproject.toml declares no project license
Deployment
Oracle HEAD, migrations and health unverified: local deployment configuration and SSH access unavailable in this session
The handoff baseline matches live main. The owner's bounded governance work precedes M1.4d but is
not yet recorded as a repository selection change. No engineering-state file was modified. Main's
empty legacy-status response is not interpreted as failed CI or as proof of every required check.
No candidate PR exists for these documents; this is not a merge-readiness assessment.
Open P0/P1 gaps remain LEDGER-GAP-001, CAMPAIGN-GAP-001, CHAIN-GAP-001,
KNOWLEDGE-GAP-001 and TARGET-RUNTIME-GAP-001. This ADR closes none of them. Oracle uncertainty
does not prevent drafting a document; it prevents claiming runner qualification or deployment sync.
1. Decision proposed
Introduce a small deterministic source-admission evaluator with a typed `SourceAdmissionReport`.
It evaluates an exact repository snapshot, declared provenance, independently attributed review
evidence and a protected policy for one explicitly named use. The first use is engineering review.
Separate three authorities:
The owner establishes the permitted-use and source/license policy, obtaining legal interpretation
where necessary. An LLM never establishes legal compatibility.
Deterministic code checks completeness, binding and compliance with those explicit policy rows.
A human reviewer dispositions ambiguity. Similarity tools and LLMs may supply advisory findings.
`ADMITTED` means the declared inputs satisfy the named policy for the named use. It never means
copyright-free, non-infringing, generally redistributable, merge-authorized or capability-qualified.
Undeclared copying can escape detection; the report must retain this limitation.
001A defines contracts and proofs in prose. It adds no Python models, scanner, workflow, dependency,
required check, automatic rewriting, model-provider connection or production admission path.
2. Scope and origin model
Origin is a set of contributions, not one file-wide exclusive label. AI editing an existing third-party
file cannot erase that file's lineage or obligations. Record contribution ranges where meaningful;
otherwise conservatively attribute the whole blob to all applicable origins.
Origin class
Required evidence
Unknown treatment
REPOSITORY_AUTHORED
contributor identity and declaration, blob identity, review reference
REVIEW_REQUIRED
AI_GENERATED
authoring tool/provider/model identifier, available version, generation evidence reference, declared inputs/external references, human review
unavailable fields explicitly identified; policy decides sufficiency, never fabricated
THIRD_PARTY_SOURCE
upstream locator and immutable revision/content digest, license evidence and attribution
REVIEW_REQUIRED
VENDORED_SOURCE
third-party lineage plus local modifications, dependency relationship and notices
REVIEW_REQUIRED
GENERATED_ARTIFACT
generator/toolchain version, input and output digests, dependency lineage
REVIEW_REQUIRED; generation is not originality
EXTERNAL_PATCH
submitter and patch identity, origin/license declaration and reviewer attribution
REVIEW_REQUIRED
UNKNOWN
exact affected blobs and missing/conflicting evidence
never ADMITTED
The first implementation evaluates the exact base-to-head change inventory and the complete input
bundle intended for its next consumer. Included unchanged context requires provenance as well.
Unexamined repository files and historical dependencies remain explicitly outside the report's claim.
Full-tree license clearance and retroactive repository-wide attribution are not prerequisites invented
by this ADR; neither may be claimed by a delta report.
Existing CI runs lint/type/tests, Bandit, pip-audit, secret scanning and lock validation. These are
separate evidence, not a license-admission implementation. NFR-010's full supply-chain requirement
is not declared complete. Locked dependency identities must accompany any dependency material
actually used; a lockfile hash alone does not prove license terms or build reproducibility.
3. Policy and permitted use
`SourcePolicy` is loaded from an owner-reviewed protected-main commit selected independently of
the candidate. Record its version, commit, blob and SHA-256 digest. Never load policy, trusted
reviewers, scan configuration or executable hooks from the candidate checkout.
Policy entries match exact material identity and declared use, not an LLM's license-family guess.
The contract carries:
- policy/schema version; approved reviewer identities and evidence-source rules;
- use profile, source classes and exact approved license-expression/evidence combinations;
- permission evidence for owner-authored material, independently of a public distribution license;
- obligations: attribution, retained notices, source availability/disclosure, redistribution limits,
modification marking and other owner-specified conditions, each with evidence of satisfaction;
- external-model disclosure permission, allowed processor/profile, redaction and retention rules;
- missing/ambiguous/unsupported handling, revision invalidation and audit retention policy.
Proposed initial use is `ENGINEERING_REVIEW`, not distribution or target use. Each run additionally
declares `LOCAL_ONLY` or an owner-approved external processor. Public repository visibility is not
used as permission to send every file or credential to a model service.
License evidence uses SPDX identifiers/expressions where applicable, or an explicit local reference
to immutable terms. Preserve AND, OR, WITH and parentheses. An OR choice needs a recorded selection;
AND retains all obligations; WITH includes the exact exception. The minimal evaluator may accept
only explicitly reviewed expression/profile rows and return REVIEW_REQUIRED for everything else.
It must not build a general legal-compatibility engine or simplify expressions by string matching.
See [SPDX 2.3 Annex D](https://spdx.github.io/spdx-spec/v2.3/SPDX-license-expressions/).
No blanket allowlist for MIT, Apache, BSD, copyleft or any other family is created here. A recognized
identifier is evidence vocabulary, not permission. An absent license is an unresolved fact, not
automatic compatibility. An owner attestation cannot waive third-party obligations.
4. Typed contracts and binding
These are semantic wire contracts for 001B, not production schemas installed by 001A.
Contract
Mandatory semantics
SourceSubject
repository identity from trusted repository metadata; base/head commit and tree IDs with hash algorithm; use profile; complete in-scope inventory
SourceItem
raw Git path encoded without lossy normalization; mode/type; base/head blob IDs; independent SHA-256 of inspected bytes; change kind; contribution classes; lineage, dependency and obligation references
OriginDeclaration
subject/content bindings, author/tool/model facts with availability discriminators, declared external references, declaration evidence identity; no invented provenance
ReviewEvidence
authenticated reviewer identity, exact item/inventory binding, decision and rationale, evidence reference/digest, timestamp and supersession/revocation state
SourcePolicyRef
protected source commit/blob; version; digest; use/processor profile and retention policy
SourceAdmissionReport
schema version; subject; inventory/declarations/reviews digests; policy reference; evaluator version; per-item decisions; overall status; sorted unique reason codes; evidence completeness; observed_at; producer/run reference; report digest
Verdict is exactly `ADMITTED | REVIEW_REQUIRED | REJECTED | INVALID`. All output includes an explicit
coverage description. A machine consumer never infers whole-repository coverage from the report name.
Use strict JSON: reject duplicate/unknown keys, unsupported schemas, non-finite numbers, coercions,
duplicate item identities and malformed hashes. Semantic v1 payloads use strings, strict integers,
booleans, nulls, objects and arrays; no floating-point fields. Hash canonical UTF-8 JSON with sorted
object keys, compact separators, no ASCII escaping and no NaN; preserve array order except documented
sets, which are sorted and deduplicated before validation. Do not normalize source-byte content.
Preimage is `blackbread.source-admission.v1` plus a zero byte plus canonical payload, excluding only
the report_digest field. Include every semantic nested binding, verdict and producer field. Test a
manually derived known-answer vector. Policy and bundle digests use distinct domain tags.
Commit objects, tree objects and included blobs are cross-checked. Renames retain before/after lineage;
deletion cannot silently remove attribution required by retained material. Symlinks, submodules,
LFS placeholders, unsupported binary formats and unsafe paths never cause implicit fetch, traversal
or code execution: return a typed unsupported/review result unless the input profile handles them.
Declarations and reports are detached from the candidate commit, avoiding a self-referential SHA.
The trusted collector binds their content after the candidate head is frozen. Reports are never
committed into the same head they purport to attest.
5. Producer and consumer authority
Artifact
Producer and consumer
Integrity / authenticity / freshness
Authority
Candidate source/declaration
IDE/contributor → trusted collector
object/digest checks; claims remain untrusted; exact snapshot
data only
Protected policy
owner-reviewed main → evaluator
authenticated retrieval plus immutable source identity; current approved revision checked by controller
rules for engineering admission only
Review evidence
authorized reviewer → evaluator
authenticated service receipt or access-controlled owner record; bind scope and check supersession
supplies a policy fact, never waives law
SourceAdmissionReport
composed collector/evaluator → grader controller and owner
digest proves consistency; authenticated run origin or current-call recomputation proves bounded producer continuity
no merge or execution authority
All serialized artifacts are caller-constructible. Recomputing a digest does not authenticate a
producer. The pilot controller obtains the source snapshot once, invokes the trusted evaluator
inside its own call, and carries that exact snapshot into grading. It never accepts a supplied
`ADMITTED` report as authority. Exported JSON is an audit copy. Import into an authoritative path is
not supported in v1; rerun the trusted evaluator instead of introducing a signing service.
Protected-base policy changes follow ordinary review and take effect only after merge; a candidate
cannot grade itself under its own proposed policy. First installation uses the existing delivery
gates; it does not demand an already-existing report from the gate being installed.
6. Deterministic outcomes and review path
Condition / reason family
Outcome
Permitted next step
Schema, identity, snapshot or digest mismatch; INCOMPLETE_INVENTORY; UNTRUSTED_REVIEW; POLICY_UNAVAILABLE
INVALID
repair evidence and rerun; no grading admission
POLICY_FORBIDS_USE; DISCLOSURE_FORBIDDEN; REQUIRED_OBLIGATION_UNSATISFIED
REJECTED
change candidate/use or obtain a separately reviewed policy decision; no grading admission
ORIGIN_UNKNOWN; LICENSE_UNKNOWN; LICENSE_EXPRESSION_UNSUPPORTED; PROVENANCE_AMBIGUOUS; REVIEW_MISSING
REVIEW_REQUIRED
quarantine and exact-scope human review; not ordinary grading
Complete matching facts; approved use; all applicable obligations evidenced
ADMITTED
pass exact admitted bundle to the named engineering consumer
Each reason code has one meaning and an item/policy reference. INVALID dominates aggregate status,
then REJECTED, then REVIEW_REQUIRED, then ADMITTED; retain every underlying reason. Unknown exceptions
produce a sanitized INVALID result, never acceptance or a partial success report.
REVIEW_REQUIRED is not an escape hatch. A restricted review-only path may inspect the material as
data only when a separately authenticated owner instruction and protected policy explicitly permit
that exact repository/head, inventory, purpose, processor and expiry. It cannot authorize an already
forbidden use or unsatisfied mandatory obligation. External transmission is separately checked.
Without that instruction, quarantine locally. A review-only grader can produce findings, never PASS.
Resolving provenance requires new evidence and reevaluation; editing a verdict or marking a model
finding false positive cannot turn REVIEW_REQUIRED into ADMITTED.
7. State, lifecycle and failure
The repository owns policy versions. An access-controlled engineering evidence directory/artifact
store owns append-only run bundles; it is separate from the campaign ledger and contains no target
evidence. No new database, key service or provenance platform is required for the pilot.
The controller owns ephemeral snapshots and run IDs. Persist evidence atomically before publishing
a report reference; a crash leaves the run in the lifecycle state INCOMPLETE — an evidence-store
state, never a published report verdict — and never replaces a previous report. Conflicting
content for the same run ID is rejected. Concurrent runs use separate namespaces and may not overwrite
each other. Cancellation prevents further processing/disclosure and records partial evidence.
Policy, use, processor, head, inventory or review-evidence changes invalidate reuse. Historical reports
remain historical. Before consumption, compare all expected bindings to the controller's current
request. A changed head never inherits a report merely because the diff appears equivalent.
Retention, access and expiry are policy inputs, fixed before activation. Do not retain raw prompts,
secrets or copied customer evidence by default. A prompt digest identifies bytes; it does not prove
their quality, legality, or truthful origin. Missing retained evidence makes a historical claim
unverifiable rather than silently trusted. Rollback disables the new consumer; it does not synthesize
an admitted report or weaken existing delivery checks.
8. Threat model and proof obligations for 001B
The adversary can author candidate source, declarations, tests, comments, local report JSON and
candidate policy files. It cannot be assumed to control the protected controller or authenticated
owner account. Compromise of those authorities is outside this pilot's claim and invalidates its
reports. All fixtures below use adjacent valid controls.
Claim / named test
Passing oracle and excluded false positive
RED or mutation proof
IP01 exact_snapshot
alternate valid head/blob/mode/base is rejected; exact bundle accepted; not merely malformed input rejection
remove one binding comparison; substituted valid input must then be wrongly admitted and test fail
IP02 complete_inventory
omitted added/renamed/context item is INVALID; complete inventory accepted
delete inventory reconciliation; omission test must fail
IP03 no_self_policy
candidate permissive policy cannot affect result; protected approved change can
load candidate policy instead; denied fixture becomes admitted and test fails
IP04 no_forged_producer
constructed ADMITTED JSON/recomputed hash never bypasses collector/evaluator; real composed evaluation runs
inject supplied intermediate instead of recomputing; invocation and behavioral oracle fail
IP05 origin_obligations
missing lineage and mixed AI/third-party contribution stay review-required; missing mandatory notice rejects
collapse origin to AI-only or omit obligation check; offending fixture is admitted and test fails
IP06 expression_semantics
AND/OR/WITH cannot be silently simplified; only exact reviewed expression/use row admits
replace exact expression matching with substring test; contrary fixtures fail
IP07 review_not_admission
restricted review needs bound owner permission and cannot produce normal admission; exact authorized review remains possible
skip purpose/processor/expiry check; disclosure spy observes forbidden call and test fails
IP08 canonical_preimage
known-answer digest matches; valid nested-field mutation with stale digest rejects
remove a semantic field from preimage; mutation test fails
IP09 lifecycle
cancellation/crash/duplicate ID cannot publish partial or overwrite complete evidence
publish before atomic completion or remove ID conflict check; storage oracle fails
IP10 no_authority_growth
evaluator/consumer never calls merge, branch-write, registry, lease, WorkOrder or target APIs on any verdict
wire forbidden call in temporary mutation; deny-all capability spy fails
Expected RED is the named property accepting a forbidden input/effect, not an unrelated syntax error.
Restore each mutation and prove GREEN. Tests are future obligations, not results achieved by this ADR.
9. Architecture feasibility and acceptance status
Architecture decision: ACCEPT WITH CHANGES for the proposed documentation boundary. The changes
relative to a broad source-clearance gate are explicit use/coverage limits, protected-base policy,
detached reports, composed verification and a non-authorizing review path.
Gate
Design evidence / remaining activation fact
Exact claim
a changed subject, unknown origin, prohibited use or unsatisfied mandatory obligation cannot yield ADMITTED under the same trusted policy
Smallest counterexample
caller submits an ADMITTED JSON for a different blob and recomputes its digest
Component authority
owner sets policy; trusted evaluator computes; grader reads; reviewer adjudicates; neither gate nor model merges
Information sufficiency
contract identifies every needed input; actual owner policy and attributable provenance are not yet installed
Adversarial construction
public JSON remains untrusted; same-call evaluation removes the injectable report seam
Producer/consumer continuity
001B CLI is first named consumer; grader pilot composes it over the same bundle
Boundary elimination
candidate never supplies effective policy or an authoritative intermediate result
Intermediate safety
001A is prose only; 001B must remain read-only and non-authorizing
Future-consumer safety
admission cannot become merge, target permission, whole-repository clearance or capability promotion
Proof oracles
IP01–IP10 specify behavioral counterexamples and mutation sensitivity; none has been run here
Seal state: DESIGN_HOLD for executable 001B. This ADR is accepted as the documentation boundary;
it does not seal the executable design while the §10 policy inputs remain unresolved. This is an
explicit activation condition inside the agreed A/B work, not a new governance project.
10. Owner policy record needed before activation
Decision
Proposed bounded default
Missing fact
Initial use
engineering review only; no distribution or target admission
owner acceptance and exact rights/obligation evidence for included material
Source/license rows
no implicit family-wide allowlist; unknowns require review
exact reviewed material/use rows and reviewer identity
Model disclosure
local-only until a specific processor/profile is approved
approved provider/model/data terms or local deployment profile
Evidence retention
finite, access-controlled run retention; no raw secrets/customer material
owner-approved interval, storage principal and deletion rule
A project-wide outbound license choice is not silently made here. It is required before claiming
distribution compatibility, which this pilot does not claim. The owner may approve concrete review
rights for original repository material without pretending it has an existing public license.
11. Bounded adoption and implementation boundary
The requested deliverable consists only of this ADR and its separate grader companion; each is
adopted by its own ADR-only pull request. Repository path is this filename at root; no
ADR-FINAL number is reserved without repository adoption.
For a later ADR-only adoption PR, the closed responsibility map is:
File
Action
Sole responsibility
Relative size
ADR-GOV-IP-PROVENANCE-001A.md
add
this engineering admission decision
primary document
AGENTS.md
modify
include the accepted governance ADR in authority references
small reference change
No other repository file is authorized by that map. Keep both engineering-state files unchanged:
the runtime selection remains M1.4d and this ADR records the finite governance work before it.
The live state model accepts milestone-shaped identifiers, not GOV identifiers, and renders the
state document from the manifest. Do not append hand-written narrative to that generated projection
or invent a runtime release to represent these documents. This task does not replace the selected
runtime slice. If adoption requires a selection transition under live authority, STOP/SPLIT and
resolve that concrete conflict before issuing an execution packet; do not widen the state machinery
inside this ADR-only change. No code/tests/workflows/license file are changed by 001A.
001B owns the smallest useful read-only evaluator and its actual CLI consumer, policy/declaration
validation, exact binding and focused proof. It does not build a universal license scanner, ingest
all historical code, modify merge-readiness semantics or implement the grader. Its exact code file
map and budget are derived after this ADR is accepted; this document is not an executor prompt.
Quality limits remain owned by config/quality-budgets.json and pyproject.toml. New responsibilities,
unavailable policy evidence, unsafe disclosure, a live authority conflict or inability to fit honestly
require STOP/SPLIT within the approved scope. They do not authorize weakening an invariant.
12. Consequences, alternatives and stopping point
This design makes declarations and policy evaluation auditable without asserting that a scanner can
prove originality. It creates a small manual-policy maintenance burden; ambiguous material needs
review. That is preferable to model-only legal approval, a blanket license-family ban, a broad
automated rewriting system or building a provenance platform before M1.4d.
Sequence is IP-001A → IP-001B → GRADER-001A → GRADER-001B → M1.4d. Both A drafts may be reviewed now;
their adoption and implementations remain separate sealable boundaries. No additional governance
initiative is appended after the advisory grader pilot. Any reproduced blocker is handled as a
bounded correction with evidence; M1.4d's budgets, locks and leases remain the next runtime work.
13. Source manifest
All repository files below were read at the protected baseline in §0. Blob IDs identify the exact
content used; they do not confer acceptance on this new ADR.
Source
Blob SHA
Extracted requirement
AGENTS.md
3b1af19aabd54876206978d16e1e1c02c16d1b17
authority order; live truth; bounded delivery
ADR-FINAL-002.md
9984aaf3ed968d14f57a530c3be7f4df960edec0
evidence integrity and honest conformance; preserve binding safety review
ADR-FINAL-004.md
4a919c45a96603a67401ddc22726c851b7e3aa69
policy minimalism, named consumer, return to vertical runtime
ADR-FINAL-007.md
dbc5265c8bf2b5ff6eab4645c6794ad1115ccaa0
candidate origin/review is separate from qualification/promotion
ADR-FINAL-009.md
05c245e8a685603e587293c32d4057b77b81313d
public PoC remains untrusted; licensing and qualification are distinct
PRD.md
01a52af7677402f87ea25d266087d64d8e69a806
NFR-002/003/009/010; CAP-008/009 preserved, not implemented here
GAP-REGISTER.md
d44264ed406107f23a830c6edaad07dad7f2898c
open gap status remains unchanged
.github/agent-delivery.json
b5e87b44011a5e3f090f401ad624870d739395cd
current delivery gates retained
.devin/rules/blackbread.md
b30f9ea16bdf66c4819ff5893b3b3443ddc3e9a6
deterministic boundaries, review and no hidden debt
pyproject.toml
442ee78f328a392ce30142682a1e2343dd15d735
quality authority; project license field absent
.github/workflows/ci.yml
3054f45c645161ce2faf0c7ddd46394d0a0a7ea1
observed existing checks, not a source-admission gate
src/blackbread/governance/engineering_state.py
eef8305c70832f3093d4023a84efc6ddaf09a91c
runtime identifiers and generated projection; no invented governance transition
.devin/skills/blackbread-engineering/references/trust-boundary-provenance.md
3bef6f6a93d6f78c95f0ac560022d06f4256431d
digest is not producer authenticity
Live baseline: [main snapshot](https://github.com/carlitotate12160-tech/BlackBread/tree/c818bd045384a3cb6f467edfd723c3dd1a4e2ca5),
[PR #106](https://github.com/carlitotate12160-tech/BlackBread/pull/106),
[ruleset](https://github.com/carlitotate12160-tech/BlackBread/rules/21644438).
Technical background: [SLSA artifact verification](https://slsa.dev/spec/v1.1/verifying-artifacts)
distinguishes verification of artifact/provenance identity and expectations. This ADR makes no SLSA
level claim and does not adopt a signing infrastructure.
