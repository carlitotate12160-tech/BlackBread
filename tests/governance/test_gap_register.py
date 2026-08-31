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
    assert '"context": "ci-ok"' in governance_gap
    assert '"context": "GitGuardian Security Checks"' in governance_gap
    assert '"required_review_thread_resolution": true' in governance_gap
    assert '"dismiss_stale_reviews_on_push": true' in governance_gap
    assert '"require_extra_approval_for_unattributed_changes": false' in governance_gap
    assert '"allowed_merge_methods": ["squash"]' in governance_gap
    assert '"bypass_actors": []' in governance_gap
    assert '"current_user_can_bypass": "never"' in governance_gap
