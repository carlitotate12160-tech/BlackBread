# BlackBread Gap Register

This register contains cross-cutting blockers that cannot be closed by source changes alone. Capability
admission blockers are recorded with their owner, milestone, and release in
`config/capability-registry.json`.

## GOV-GAP-001 — Live main ruleset is not verified against the machine contract

- **Status:** CLOSED
- **Severity:** P0 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** R0 and every real-target release
- **Closed at:** 2026-08-31T16:39:39+07:00
- **Closure evidence:** the live `main-branch-protection` ruleset (`21644438`) was read from GitHub
  after alignment and matches `.github/agent-delivery.json` and `.github/BRANCH-PROTECTION.md`. The
  legacy `main-approval-required` ruleset (`21698082`) is disabled and retained only as rollback evidence. The
  verified ruleset enforces: deletion protection, non-fast-forward, required linear history,
  required pull request with solo-developer settings (`required_approving_review_count: 0`,
  `require_code_owner_review: false`, `require_last_push_approval: false`,
  `dismiss_stale_reviews_on_push: true`, `required_review_thread_resolution: true`,
  `require_extra_approval_for_unattributed_changes: false`, `allowed_merge_methods: ["squash"]`),
  required status checks (`ci-ok` and `GitGuardian Security Checks`), CodeQL code scanning
  (`high_or_higher` security alerts and `errors` tool/analysis alerts), strict branch currency,
  and no bypass actors (`bypass_actors: []`, `current_user_can_bypass: "never"`).
- **Verification:** captured live ruleset snapshot below, fetched from
  `https://api.github.com/repos/carlitotate12160-tech/BlackBread/rulesets/21644438`, matches the
  machine contract.
- **Compensating control:** N/A.

<details>
<summary>Verified live ruleset snapshot (2026-08-31T16:39:39+07:00)</summary>

```json
{
  "id": 21644438,
  "name": "main-branch-protection",
  "target": "branch",
  "source_type": "Repository",
  "source": "carlitotate12160-tech/BlackBread",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "exclude": [],
      "include": ["refs/heads/main"]
    }
  },
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          {"context": "ci-ok", "integration_id": 15368},
          {"context": "GitGuardian Security Checks", "integration_id": 46505}
        ]
      }
    },
    {
      "type": "code_scanning",
      "parameters": {
        "code_scanning_tools": [
          {
            "tool": "CodeQL",
            "security_alerts_threshold": "high_or_higher",
            "alerts_threshold": "errors"
          }
        ]
      }
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "required_reviewers": [],
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "require_extra_approval_for_unattributed_changes": false,
        "allowed_merge_methods": ["squash"]
      }
    }
  ],
  "bypass_actors": [],
  "current_user_can_bypass": "never"
}
```

</details>

<details>
<summary>Repository ruleset listing and legacy ruleset (2026-08-31)</summary>

The repository-wide ruleset listing confirms that only `main-branch-protection` (`21644438`) is
`active` for `branch` targets and that `main-approval-required` (`21698082`) is `disabled`:

```json
[
  {
    "id": 21698082,
    "name": "main-approval-required",
    "target": "branch",
    "source_type": "Repository",
    "source": "carlitotate12160-tech/BlackBread",
    "enforcement": "disabled"
  },
  {
    "id": 21644438,
    "name": "main-branch-protection",
    "target": "branch",
    "source_type": "Repository",
    "source": "carlitotate12160-tech/BlackBread",
    "enforcement": "active"
  },
  {
    "id": 21644473,
    "name": "tag-protection",
    "target": "tag",
    "source_type": "Repository",
    "source": "carlitotate12160-tech/BlackBread",
    "enforcement": "active"
  }
]
```

The disabled `main-approval-required` ruleset (`21698082`) has `enforcement: disabled` and therefore
has no live effect; it is retained only as rollback evidence:

```json
{
  "id": 21698082,
  "name": "main-approval-required",
  "target": "branch",
  "enforcement": "disabled",
  "conditions": {
    "ref_name": {
      "exclude": [],
      "include": ["refs/heads/main"]
    }
  },
  "rules": [
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "required_reviewers": [],
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "require_extra_approval_for_unattributed_changes": true,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    }
  ],
  "bypass_actors": [
    {
      "actor_id": 1144995,
      "actor_type": "Integration",
      "bypass_mode": "pull_request"
    }
  ],
  "current_user_can_bypass": "never"
}
```

</details>

## GOV-GAP-002 through GOV-GAP-005 — ai-review-gate activation (WITHDRAWN)

- **Status:** CLOSED (WITHDRAWN 2026-08-30)
- **Owner:** repository administrator
- **Superseded by:** removal of the repository-owned `ai-review-gate` apparatus.
- **Resolution:** the repository-owned `ai-review-gate` workflow, its evaluator
  (`src/blackbread/governance/ai_review_gate.py`), and `docs/AI-REVIEW-SETUP.md` were removed. For a
  solo-developer repository the gate enforced nothing — it was `bootstrap_not_enforced` and never a
  required status check — while producing a persistent failing check on every pull request and
  cascading `issue_comment` runs. The four sub-gaps it tracked are moot once the gate no longer
  exists: issue_comment SHA targeting (former GOV-GAP-002), review-thread resolution inside the gate
  (former GOV-GAP-003), controller concurrency ordering (former GOV-GAP-004), and thread-resolution
  wake-up (former GOV-GAP-005). PR-Agent (DeepSeek) and CodeRabbit remain active advisory reviewers.
  For safety-critical PRs, the current-head PR-Agent review is binding. For non-safety-critical PRs,
  CodeRabbit is the primary advisory reviewer and PR-Agent may provide fallback. Actionable comments
  must be dispositioned before merge; enforcement relies on first-party CI (`quality`, `tests`,
  `security`, `governance`), `GitGuardian Security Checks`, and protected-main review-thread
  resolution.
- **Verification:**
  `tests/governance/test_governance_contract.py::test_ai_review_gate_apparatus_is_fully_removed`.

## GOV-GAP-006 — Post-merge `ENGINEERING-STATE.md` main SHA pointer automation missing

- **Status:** OPEN
- **Severity:** P1 governance
- **Owner:** repository administrator
- **Target milestone:** M0 governance hardening
- **Blocks:** none — a stale or missing SHA pointer is not a merge blocker, per AGENTS.md and
  `.devin/rules/blackbread.md` preflight rule #10.
- **Current evidence:** PR #43 was squash-merged to `main` at `f721f72`. The `ENGINEERING-STATE.md`
  `PR-M1.3b2b` release record was manually updated to `f721f72` on branch `gov-gap-006-state-update`
  (a PR-level release record is permitted). No protected-main-baseline pointer was added, consistent
  with the no-hand-typing policy. The required post-merge automation is still missing, so
  `GOV-GAP-006` remains open.
- **Required closure:** a required post-merge automation step (e.g., a `push`/`merge` triggered
  GitHub Actions workflow with `contents: write` and a protected-branch bypass for the automation
  identity, or a repository rule that stamps the merged SHA) updates the
  `ENGINEERING-STATE.md` `Protected main baseline` pointer immediately after a PR is squash-merged
  to `main`. Manual edits to that pointer are no longer needed and no longer allowed.
- **Verification:** after a merge, the pointer matches the actual `main` HEAD SHA within one
  workflow run, without creating a follow-up PR.
- **Compensating control:** until the automation is live, `ENGINEERING-STATE.md` may contain a
  hand-typed or stale SHA pointer, which must be cross-checked against live GitHub. The file's own
  header and preflight rule #10 state that it is a checkpoint, not a substitute for live GitHub.

## LEDGER-GAP-001 — R0 trust-spine integration remains incomplete

- **Status:** OPEN
- **Severity:** P0 architecture
- **Owner:** trust-spine
- **Target milestone:** M1
- **Blocks:** R0 and every target-facing release
- **Current evidence:** the tenant-bound, hash-versioned PostgreSQL ledger supports serialized append,
  replay verification, immutable envelope hashing, and database-level UPDATE/DELETE/TRUNCATE denial.
  PR #35 added durable, deterministic `ScopeRoot` projection from the ledger, frozen NetworkX rebuild,
  and state-root v1. Conductor, Policy Kernel v1, execution leases, dual kill-switch, and the full
  authenticated trust-spine runtime are not yet integrated.
- **Required closure:** wire every trust-spine publisher through the ledger; implement projector/rebuild,
  deterministic Conductor and Policy Kernel paths, lease and kill-switch enforcement, and database-role
  tenant isolation; prove replay and negative scope/lease paths end to end.
- **Verification:** `tests/ledger/` plus future trust-spine integration suites and the versioned R0
  conformance record.
- **Compensating control:** none. The ledger slice may merge, but R0/M1 and target-facing execution
  remain blocked until closure evidence is attached.

## GRAPH-GAP-001 — Attestation v2 head lacks a truthful durable projection schema

- **Status:** OPEN
- **Severity:** P1 architecture
- **Owner:** trust-spine
- **Target milestone:** M1.3b3
- **Blocks:** M1.3 completion, R0, and every target-facing release
- **Proposed closure evidence (PR #48):**
  - Migration `0006_m1_temporal_scope_graph` (PR #45 / b3a) added the temporal persistence schema
    with immutable revision-lineage, stable-root, and atomic publication tables, plus RLS tenant
    isolation and exact-provenance enforcement triggers.
  - `rebuild_and_publish_temporal_projection()` (b3a) persists v2-head publications durably through
    the temporal path without weakening exact source-event provenance.
  - `load_temporal_projection()` (b3b-1) performs a verified cold reconstruction from durable
    PostgreSQL rows: reassembles `TemporalLineage`, recomputes state-root v2, and verifies it equals
    the stored snapshot — fail-closed on any mismatch (tampered state-root, altered/missing/injected
    revision, or head membership mismatch).
  - The v1 scope path (`rebuild_scope_projection`) correctly rejects v2 provenance with a permanent
    routing message; v2 heads publish exclusively through the durable temporal path.
  - Real-PostgreSQL cold-rebuild proofs in `tests/graph/test_temporal_reconstruction.py` verify: v1
    cold-rebuild, v2 cold-rebuild, revision durability with tamper detection, state-root tamper
    detection, tenant isolation, source-event binding, v2 temporal-path publication, and v1 scope-path
    rejection of v2 provenance.
- **Verification:** `tests/graph/test_temporal_reconstruction.py` (real PostgreSQL).

## GRAPH-GAP-002 — Cold-reconstruction integrity: stable-roots unverified

- **Status:** CLOSED
- **Severity:** P1 architecture
- **Owner:** trust-spine
- **Target milestone:** M1.3b3b-HARDEN
- **Blocks:** none
- **Closed at:** 2026-09-02
- **Closure evidence:** Added F1 checks to verify `cold.roots` against the lineage-derived stable-root identity set. Added F4 defense-in-depth tenant assertion in `_reconstruct`. Proved via `test_stable_roots_tamper` and `test_real_cross_tenant_isolation`.
- **Verification:** `tests/graph/test_temporal_reconstruction.py` (real PostgreSQL).
