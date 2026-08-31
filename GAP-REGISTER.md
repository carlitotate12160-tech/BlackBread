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
  wake-up (former GOV-GAP-005). Qodo and CodeRabbit remain active advisory reviewers whose actionable
  comments must be dispositioned before merge; enforcement relies on first-party CI (`quality`,
  `tests`, `security`, `governance`), `GitGuardian Security Checks`, and protected-main review-thread
  resolution.
- **Verification:**
  `tests/governance/test_governance_contract.py::test_ai_review_gate_apparatus_is_fully_removed`.

## LEDGER-GAP-001 — R0 trust-spine integration remains incomplete

- **Status:** OPEN
- **Severity:** P0 architecture
- **Owner:** trust-spine
- **Target milestone:** M1
- **Blocks:** R0 and every target-facing release
- **Current evidence:** the tenant-bound, hash-versioned PostgreSQL ledger supports serialized append,
  replay verification, immutable envelope hashing, and database-level UPDATE/DELETE/TRUNCATE denial.
  Graph projection, NetworkX rebuild, Conductor, Policy Kernel v1, execution leases, dual kill-switch,
  and authenticated PostgreSQL row-level tenant context are not implemented.
- **Required closure:** wire every trust-spine publisher through the ledger; implement projector/rebuild,
  deterministic Conductor and Policy Kernel paths, lease and kill-switch enforcement, and database-role
  tenant isolation; prove replay and negative scope/lease paths end to end.
- **Verification:** `tests/ledger/` plus future trust-spine integration suites and the versioned R0
  conformance record.
- **Compensating control:** none. The ledger slice may merge, but R0/M1 and target-facing execution
  remain blocked until closure evidence is attached.
