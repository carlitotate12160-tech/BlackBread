from pathlib import Path

ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / ".devin/skills/blackbread-engineering"
REFERENCES = SKILL_ROOT / "references"

PACKETS = (
    "workflow-loop.md",
    "design-seal-template.md",
    "execution-prompt-template.md",
    "qualification-runbook-template.md",
    "correction-packet-template.md",
)


def _read(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def test_role_separated_packets_exist_and_are_routed_from_the_skill() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for packet in PACKETS:
        assert (REFERENCES / packet).is_file()
        assert f"references/{packet}" in skill


def test_implementation_packet_remains_compact_and_role_scoped() -> None:
    packet = _read("execution-prompt-template.md")

    assert len(packet.splitlines()) <= 180
    assert "Architecture Feasibility Gate" not in packet
    assert "FINAL CURRENT-HEAD SEAL" not in packet
    assert "MERGEABLE or NOT MERGEABLE" not in packet


def test_packets_bind_each_handoff_to_immutable_identity() -> None:
    assert "DESIGN_SEAL_ID: <slice>@<protected-base-sha>" in _read("design-seal-template.md")
    implementation = _read("execution-prompt-template.md")
    assert "DESIGN_SEAL_ID:" in implementation
    assert "PROTECTED_BASE_SHA:" in implementation
    assert "COMMIT_SHA:" in _read("qualification-runbook-template.md")
    assert "REVIEWED_HEAD_SHA:" in _read("correction-packet-template.md")


def test_fix_mode_binds_correction_identity_before_edits() -> None:
    implementation = _read("execution-prompt-template.md")
    correction = _read("correction-packet-template.md")

    for packet in (implementation, correction):
        assert "CORRECTION_PACKET_ID:" in packet
        assert "REVIEWED_HEAD_SHA:" in packet

    drift_check = implementation.split("## Drift check", 1)[1]
    assert "CORRECTION_PACKET_ID" in drift_check
    assert "REVIEWED_HEAD_SHA" in drift_check


def test_implementation_return_states_cover_stop_outcomes() -> None:
    state_lines = [
        line
        for line in _read("execution-prompt-template.md").splitlines()
        if line.startswith("STATE:")
    ]

    assert len(state_lines) == 1
    for outcome in ("DESIGN_DRIFT", "DESIGN_FAILURE", "SPLIT_REQUIRED"):
        assert outcome in state_lines[0]
    assert "STOPPED" not in state_lines[0]


def test_workflow_qualification_leg_and_comment_dispositions() -> None:
    workflow = _read("workflow-loop.md")
    flow = workflow.split("## State flow", 1)[1].split("```", 2)[1]

    for state in (
        "QUALIFICATION_REQUIRED",
        "QUALIFIED",
        "QUALIFICATION_FAILED",
        "CORRECTION_REQUIRED",
    ):
        assert state in flow
    assert "QUALIFICATION_FAILED ->" in flow
    assert "never retries automatically" in workflow
    for disposition in (
        "fixed",
        "deferred-with-authority",
        "stale",
        "false-positive-with-evidence",
    ):
        assert disposition in workflow


def test_workflow_forbids_automatic_retry_and_merge_decisions() -> None:
    workflow = _read("workflow-loop.md")

    assert "must not trigger an automatic retry" in workflow
    assert "the final merge action" in workflow
    assert "Add orchestration software only after the pilot" in workflow
