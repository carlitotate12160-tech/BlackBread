import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _load_snapshot_and_contract():
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")
    governance_gap = gaps.split("## GOV-GAP-001", maxsplit=1)[1].split(
        "## GOV-GAP-002", maxsplit=1
    )[0]
    fence = governance_gap.split("```json", maxsplit=1)[1].split("```", maxsplit=1)[0]
    snapshot = json.loads(fence)
    delivery = json.loads((ROOT / ".github/agent-delivery.json").read_text(encoding="utf-8"))[
        "agent_delivery"
    ]
    branch_protection = (ROOT / ".github/BRANCH-PROTECTION.md").read_text(encoding="utf-8")
    return snapshot, delivery, branch_protection, governance_gap


def _rules_by_type(snapshot: dict) -> dict:
    return {rule["type"]: rule for rule in snapshot["rules"]}


def test_gov_gap_001_status_and_snapshot_structure() -> None:
    snapshot, delivery, _, gap = _load_snapshot_and_contract()
    assert "**Status:** CLOSED" in gap
    assert "**Severity:** P0 governance" in gap
    assert "**Blocks:** R0 and every real-target release" in gap
    assert "**Closure evidence:**" in gap
    assert snapshot["id"] == delivery["ruleset_id"]
    assert snapshot["name"] == "main-branch-protection"
    assert snapshot["target"] == "branch"
    assert snapshot["enforcement"] == "active"
    assert snapshot["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert snapshot["bypass_actors"] == []
    assert snapshot["current_user_can_bypass"] == "never"
    assert delivery["pull_request_required"] is True
    assert delivery["direct_push_main_allowed"] is False
    assert delivery["force_push_allowed"] is False


def test_gov_gap_001_branch_protection_rules_present() -> None:
    snapshot, _, _, _ = _load_snapshot_and_contract()
    rules = _rules_by_type(snapshot)
    assert rules["deletion"] == {"type": "deletion"}
    assert rules["non_fast_forward"] == {"type": "non_fast_forward"}
    assert rules["required_linear_history"] == {"type": "required_linear_history"}


def test_gov_gap_001_required_status_checks_match_contract() -> None:
    snapshot, delivery, branch_protection, _ = _load_snapshot_and_contract()
    rules = _rules_by_type(snapshot)
    status = rules["required_status_checks"]["parameters"]
    assert status["strict_required_status_checks_policy"] == delivery["require_branch_up_to_date"]
    assert status["do_not_enforce_on_create"] is False
    contexts = [check["context"] for check in status["required_status_checks"]]
    assert contexts == delivery["required_status_checks"]
    assert contexts == ["ci-ok", "GitGuardian Security Checks"]
    assert "ci-ok" in branch_protection
    assert "GitGuardian Security Checks" in branch_protection


def test_gov_gap_001_code_scanning_matches_contract() -> None:
    snapshot, _, branch_protection, _ = _load_snapshot_and_contract()
    rules = _rules_by_type(snapshot)
    code_scanning = rules["code_scanning"]["parameters"]["code_scanning_tools"][0]
    assert code_scanning["tool"] == "CodeQL"
    assert code_scanning["security_alerts_threshold"] == "high_or_higher"
    assert code_scanning["alerts_threshold"] == "errors"
    assert "CodeQL" in branch_protection
    assert "high_or_higher" in branch_protection
    assert "errors" in branch_protection


def test_gov_gap_001_pull_request_controls_match_contract() -> None:
    snapshot, delivery, branch_protection, _ = _load_snapshot_and_contract()
    rules = _rules_by_type(snapshot)
    pull = rules["pull_request"]["parameters"]
    assert pull["required_approving_review_count"] == delivery["required_approving_reviews"]
    assert pull["require_code_owner_review"] == delivery["require_code_owner_review"]
    assert pull["require_last_push_approval"] == delivery["require_last_push_approval"]
    assert pull["dismiss_stale_reviews_on_push"] == delivery["dismiss_stale_reviews"]
    assert pull["required_review_thread_resolution"] == delivery["require_review_thread_resolution"]
    assert (
        pull["require_extra_approval_for_unattributed_changes"]
        == delivery["require_extra_approval_for_unattributed_changes"]
    )
    assert pull["allowed_merge_methods"] == ["squash"]
    assert "squash" in branch_protection
    assert "solo-developer" in branch_protection
