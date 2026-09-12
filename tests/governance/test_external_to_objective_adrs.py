import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_external_to_objective_decisions_are_small_accepted_adrs() -> None:
    titles = {
        "ADR-FINAL-005.md": "Campaign Authority Envelope",
        "ADR-FINAL-006.md": "Access Context and Attack-Path Chaining",
        "ADR-FINAL-007.md": "Ephemeral Target Runtime",
        "ADR-FINAL-008.md": "Bounded Lateral Movement",
        "ADR-FINAL-009.md": "Rapid N-Day Response",
    }

    for path, title in titles.items():
        decision = read_repo_file(path)
        assert title in decision
        assert "**Status:** ACCEPTED" in decision
        assert "**Implementation status:** DECIDED only" in decision
        assert "does not authorize target-facing execution" in decision


def test_campaign_authority_is_a_ceiling_not_per_hop_execution_permission() -> None:
    decision = read_repo_file("ADR-FINAL-005.md")

    assert "Verified External-to-Objective Attack Path" in decision
    assert "authority ceiling" in decision
    assert "not execution permission" in decision
    assert "without per-hop human approval" in decision
    assert "supersedes earlier references to a separate human approval" in decision
    assert "Policy evaluates every exact effect" in decision
    assert "without advance blue-team notice" in decision
    assert "cannot guarantee non-detection" in decision


def test_chaining_preserves_atomic_effects_and_action_proposal_v1() -> None:
    decision = read_repo_file("ADR-FINAL-006.md")

    assert "ActionProposal v1 remains byte-stable" in decision
    assert "source_access_context_ref" in decision
    assert "execution_route_ref" in decision
    assert "expected_security_transition" in decision
    assert "one opaque multi-step proposal" in decision
    assert "re-read a new coherent world snapshot" in decision
    assert "no fixed Scout-to-Strike-to-Exploit pipeline" in decision


def test_target_runtime_is_ephemeral_and_not_a_hidden_mission_brain() -> None:
    decision = read_repo_file("ADR-FINAL-007.md")

    assert "no permanent pre-installed BlackBread component" in decision
    assert "does not contain an LLM" in decision
    assert "cannot choose follow-up work" in decision
    assert "not durable covert C2" in decision
    assert "cleanup evidence" in decision
    assert "screenshot is supporting evidence" in decision
    assert "does not require a rewrite of the five agents or control plane" in decision
    assert "An executable payload is a reviewed capability artifact" in decision
    assert "evaluate Rust as the preferred default" in decision


def test_lateral_movement_is_dedicated_bounded_and_not_smuggled() -> None:
    decision = read_repo_file("ADR-FINAL-008.md")
    registry = json.loads(read_repo_file("config/capability-registry.json"))
    objective_read = next(
        capability
        for capability in registry["capabilities"]
        if capability["id"] == "post_exploit.objective_read.v1"
    )

    assert "bounded lateral movement" in decision
    assert "dedicated capability" in decision
    assert "new ActionProposal" in decision
    assert "no unrestricted lateral movement" in decision
    assert "objective_read.v1 remains prohibited" in decision
    assert "lateral_movement" in objective_read["prohibited_effects"]


def test_zero_day_is_a_non_goal_and_rapid_n_day_cannot_self_promote() -> None:
    decision = read_repo_file("ADR-FINAL-009.md")

    assert "zero-day hunting and weaponization are product non-goals" in decision
    assert "Rapid N-Day" in decision
    assert "24-hour objective applies to ingestion and triage" in decision
    assert "does not promise a client-executable exploit within 24 hours" in decision
    assert "public exploit code is untrusted research input" in decision
    assert "cannot activate a capability" in decision
    assert "NOVEL_VULNERABILITY_CANDIDATE" in decision


def test_authority_cross_references_and_blocking_gaps_are_explicit() -> None:
    product = read_repo_file("PRD.md")
    agents = read_repo_file("AGENTS.md")
    rules = read_repo_file(".devin/rules/blackbread.md")
    gaps = read_repo_file("GAP-REGISTER.md")

    for number in range(5, 10):
        name = f"ADR-FINAL-{number:03d}.md"
        assert name in product
        assert name in agents
        assert name in rules

    assert "CHAIN-GAP-001" in gaps
    assert "TARGET-RUNTIME-GAP-001" in gaps
    assert "N-DAY-GAP-001" in gaps
    assert "full kill-chain capability remains non-executable" in gaps
