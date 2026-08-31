import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_gov_gap_001_is_closed_with_live_ruleset_snapshot() -> None:
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")
    governance_gap = gaps.split("## GOV-GAP-001", maxsplit=1)[1].split(
        "## GOV-GAP-002", maxsplit=1
    )[0]

    assert "**Status:** CLOSED" in governance_gap
    assert "**Severity:** P0 governance" in governance_gap
    assert "**Blocks:** R0 and every real-target release" in governance_gap
    assert "**Closure evidence:**" in governance_gap

    fence = governance_gap.split("```json", maxsplit=1)[1].split("```", maxsplit=1)[0]
    snapshot = json.loads(fence)

    assert snapshot["id"] == 21644438
    assert snapshot["name"] == "main-branch-protection"
    assert snapshot["target"] == "branch"
    assert snapshot["enforcement"] == "active"
    assert snapshot["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert snapshot["bypass_actors"] == []
    assert snapshot["current_user_can_bypass"] == "never"

    rules_by_type = {rule["type"]: rule for rule in snapshot["rules"]}

    assert rules_by_type["deletion"] == {"type": "deletion"}
    assert rules_by_type["non_fast_forward"] == {"type": "non_fast_forward"}
    assert rules_by_type["required_linear_history"] == {"type": "required_linear_history"}

    status = rules_by_type["required_status_checks"]["parameters"]
    assert status["strict_required_status_checks_policy"] is True
    assert status["do_not_enforce_on_create"] is False
    contexts = [check["context"] for check in status["required_status_checks"]]
    assert contexts == ["ci-ok", "GitGuardian Security Checks"]

    delivery = json.loads((ROOT / ".github/agent-delivery.json").read_text(encoding="utf-8"))
    assert delivery["agent_delivery"]["required_status_checks"] == contexts

    code_scanning = rules_by_type["code_scanning"]["parameters"]["code_scanning_tools"][0]
    assert code_scanning["tool"] == "CodeQL"
    assert code_scanning["security_alerts_threshold"] == "high_or_higher"
    assert code_scanning["alerts_threshold"] == "errors"

    pull = rules_by_type["pull_request"]["parameters"]
    assert pull["required_approving_review_count"] == 0
    assert pull["require_code_owner_review"] is False
    assert pull["require_last_push_approval"] is False
    assert pull["dismiss_stale_reviews_on_push"] is True
    assert pull["required_review_thread_resolution"] is True
    assert pull["require_extra_approval_for_unattributed_changes"] is False
    assert pull["allowed_merge_methods"] == ["squash"]
