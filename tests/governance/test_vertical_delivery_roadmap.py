from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def read_repo_file(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_vertical_delivery_decision_is_repository_authority():
    decision = read_repo_file("ADR-FINAL-004.md")
    foundation = read_repo_file("ADR-FINAL-002.md")
    campaign = read_repo_file("ADR-FINAL-003.md")
    product = read_repo_file("PRD.md")

    assert "Status:** ACCEPTED" in decision
    assert "ADR-FINAL-004.md" in foundation
    assert "ADR-FINAL-004.md" in campaign
    assert "ADR-FINAL-004.md" in product


def test_policy_authorizes_effects_without_selecting_agent_strategy():
    decision = read_repo_file("ADR-FINAL-004.md")

    assert "Policy outcome is invariant under strategy metadata" in decision
    assert "SHALL NOT change admission" in decision
    assert "Policy SHALL NOT require a static Scout-to-Strike-to-Exploit sequence" in decision
    assert "or completion of a playbook" in decision
    assert "a concrete forbidden effect" in decision
    assert "an adjacent positive control" in decision


def test_roadmap_requires_balanced_executable_vertical_slices():
    decision = read_repo_file("ADR-FINAL-004.md")

    assert "proposal -> decision -> work order -> outcome -> ledger" in decision
    assert "two consecutive release-bearing slices" in decision
    assert "named consumer" in decision
    assert "CyberTerrainGraph" in decision
    assert "AttackPathGraph" in decision
    assert "ControlAssessmentProjection" in decision
    assert "CampaignProjection" in decision
    assert "the Passive Scout loop exist" in decision
    assert "W5 — restricted Strike + Report" in decision


def test_roadmap_does_not_claim_runtime_or_target_release():
    decision = read_repo_file("ADR-FINAL-004.md")

    assert "does not implement an agent" in decision
    assert "does not admit a capability" in decision
    assert "does not authorize target-facing execution" in decision
    assert "does not claim parity with NodeZero" in decision
