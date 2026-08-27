import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
ACTIVE_CONTRACTS = (
    ROOT / "ADR-FINAL-002.md",
    ROOT / "PRD.md",
    ROOT / ".devin/rules/blackbread.md",
    ROOT / ".devin/skills/build-blackbread-agent/SKILL.md",
)
REQUIRED_CAPABILITY_FIELDS = {
    "id",
    "owner_agent",
    "adapter",
    "tool_candidates",
    "supply_chain_pin",
    "lifecycle",
    "risk_class",
    "target_identity_tier",
    "approval",
    "network_path",
    "input_schema",
    "output_schema",
    "budget",
    "evidence_oracle",
    "cleanup",
    "prohibited_effects",
    "admission",
}


def load_registry() -> dict[str, object]:
    path = ROOT / "config/capability-registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_adr_is_accepted_without_claiming_implementation_complete() -> None:
    adr = (ROOT / "ADR-FINAL-002.md").read_text(encoding="utf-8")

    assert "**Status:** Accepted" in adr
    assert "**Implementation status:** M0 foundation only" in adr


def test_active_contracts_do_not_inherit_agent_alpha_authority() -> None:
    for path in ACTIVE_CONTRACTS:
        content = path.read_text(encoding="utf-8")
        if path.name == "ADR-FINAL-002.md":
            content = content.replace(
                "Agent-Alpha is historical input only and has no authority over\nBlackBread.",
                "",
            )
        assert "Agent-Alpha" not in content
        assert "ADR-FINAL-001" not in content
        assert "alpha's" not in content.lower()
        assert "alpha lacked" not in content.lower()


def test_capability_registry_is_default_deny_and_has_unique_ids() -> None:
    registry = load_registry()
    capabilities = registry["capabilities"]

    assert registry["default_decision"] == "DENY"
    assert isinstance(capabilities, list)
    ids = [capability["id"] for capability in capabilities]
    assert len(ids) == len(set(ids))


def test_capability_entries_are_complete_and_explicitly_blocked() -> None:
    registry = load_registry()
    allowed_agents = set(registry["allowed_agents"])

    for capability in registry["capabilities"]:
        assert capability.keys() >= REQUIRED_CAPABILITY_FIELDS
        assert capability["owner_agent"] in allowed_agents
        assert capability["tool_candidates"]
        assert capability["prohibited_effects"]
        assert capability["admission"]["owner"]
        assert capability["admission"]["target_milestone"]
        assert capability["admission"]["blocking_release"]
        if capability["lifecycle"] in {"PLANNED", "ON_HOLD"}:
            assert capability["supply_chain_pin"] is None
            assert capability["admission"]["blockers"]


def test_pyproject_enforces_documented_quality_gates() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff_rules = set(config["tool"]["ruff"]["lint"]["select"])
    dev_dependencies = " ".join(config["dependency-groups"]["dev"])

    assert {"S", "ASYNC", "PL", "C90"} <= ruff_rules
    assert config["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"] == 10
    assert config["tool"]["coverage"]["report"]["fail_under"] == 80
    for package in ("pytest-cov", "pytest-randomly", "pytest-timeout", "bandit", "pip-audit"):
        assert package in dev_dependencies


def test_ci_defines_required_non_optional_jobs() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    for job in ("quality:", "tests:", "security:", "governance:"):
        assert job in workflow
    assert "continue-on-error" not in workflow
    assert "pytest.skip" not in workflow


def test_unenforced_branch_checks_are_recorded_as_release_blocker() -> None:
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")

    assert "GOV-GAP-001" in gaps
    assert "**Status:** OPEN" in gaps
    assert "**Severity:** P0 governance" in gaps
    assert "**Blocks:** R0 and every real-target release" in gaps
