import json
import re
import tomllib
from pathlib import Path

import yaml

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
REQUIRED_CAPABILITY_IDS = {
    "scout.passive_asset_intelligence.v1",
    "scout.dns_tls_http_observe.v1",
    "scout.network_service_observe.v1",
    "scout.route_browser_observe.v1",
    "scout.public_artifact_secret_detect.v1",
    "scout.discovery_signature.v1",
    "strike.credential_intelligence_offline.v1",
    "strike.authentication_validate.v1",
    "strike.authorization_differential.v1",
    "strike.service_vulnerability_verify.v1",
    "exploit.controlled_proof.v1",
    "post_exploit.objective_read.v1",
    "report.evidence_build.v1",
}
ALLOWED_LIFECYCLES = {
    "PLANNED",
    "ON_HOLD",
    "RESEARCH_DRAFT",
    "STATIC_REVIEWED",
    "FIXTURE_VERIFIED",
    "NEGATIVE_CONTROL_VERIFIED",
    "LAB_PROVEN",
    "SAFETY_REVIEWED",
    "CLIENT_ELIGIBLE",
    "EXACT_TARGET_APPROVED",
    "FIELD_OBSERVED",
    "FIELD_PROVEN",
    "REPEATABLE",
    "SUSPENDED",
    "RETIRED",
}
REQUIRED_BLOCKER_FIELDS = {
    "id",
    "status",
    "severity",
    "owner",
    "target_milestone",
    "blocking_release",
    "verification",
    "closure_evidence",
}
REQUIRED_CI_COMMANDS = {
    "quality": ("uv run ruff check .", "uv run ruff format --check .", "uv run mypy"),
    "tests": ("uv run pytest",),
    "security": ("uv run bandit", "uv run pip-audit", "./gitleaks git"),
    "governance": ("uv lock --check", "uv run pytest tests/governance --no-cov"),
}


def load_registry() -> dict[str, object]:
    path = ROOT / "config/capability-registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_workflow() -> dict[str, object]:
    path = ROOT / ".github/workflows/ci.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


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


def test_capability_registry_is_default_deny_and_has_binding_ids() -> None:
    registry = load_registry()
    capabilities = registry["capabilities"]

    assert registry["default_decision"] == "DENY"
    assert isinstance(capabilities, list)
    ids = [capability["id"] for capability in capabilities]
    assert set(ids) == REQUIRED_CAPABILITY_IDS
    assert len(ids) == len(set(ids))


def test_capability_entries_are_complete_and_explicitly_blocked() -> None:
    registry = load_registry()
    allowed_agents = set(registry["allowed_agents"])

    for capability in registry["capabilities"]:
        assert capability.keys() >= REQUIRED_CAPABILITY_FIELDS
        assert capability["owner_agent"] in allowed_agents
        assert capability["lifecycle"] in ALLOWED_LIFECYCLES
        assert capability["tool_candidates"]
        assert capability["prohibited_effects"]
        assert capability["admission"]["owner"]
        assert capability["admission"]["target_milestone"]
        assert capability["admission"]["blocking_release"]
        if capability["lifecycle"] in {"PLANNED", "ON_HOLD"}:
            assert capability["supply_chain_pin"] is None
            assert capability["admission"]["blockers"]
        for blocker in capability["admission"]["blockers"]:
            assert blocker.keys() >= REQUIRED_BLOCKER_FIELDS
            assert blocker["status"] == "OPEN"
            assert blocker["severity"] in {"P0", "P1"}
            assert blocker["owner"] == capability["admission"]["owner"]
            assert blocker["target_milestone"] == capability["admission"]["target_milestone"]
            assert blocker["blocking_release"] == capability["admission"]["blocking_release"]
            assert blocker["verification"].startswith("tests/")
            assert blocker["closure_evidence"] is None


def test_prd_requirements_use_canonical_explicit_states() -> None:
    prd = (ROOT / "PRD.md").read_text(encoding="utf-8")
    requirements = re.findall(
        r"`([A-Z]+-[0-9]{3}) \[(DECIDED|IMPLEMENTED|VERIFIED|RELEASED)\]`", prd
    )
    ids = [requirement_id for requirement_id, _ in requirements]

    assert len(ids) == len(set(ids))
    assert {f"CAP-{number:03d}" for number in range(1, 8)} <= set(ids)


def test_pyproject_enforces_documented_quality_gates() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff_rules = set(config["tool"]["ruff"]["lint"]["select"])
    dev_dependencies = " ".join(config["dependency-groups"]["dev"])

    assert {"S", "ASYNC", "PL", "C90"} <= ruff_rules
    assert config["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"] == 10
    assert config["tool"]["coverage"]["report"]["fail_under"] == 80
    for package in (
        "pytest-cov",
        "pytest-randomly",
        "pytest-timeout",
        "pyyaml",
        "bandit",
        "pip-audit",
    ):
        assert package in dev_dependencies


def test_ci_defines_required_non_optional_jobs() -> None:
    workflow = load_workflow()
    triggers = workflow["on"]
    jobs = workflow["jobs"]

    assert {"pull_request", "push"} <= triggers.keys()
    assert triggers["push"]["branches"] == ["main"]
    assert jobs.keys() >= REQUIRED_CI_COMMANDS.keys()
    for job_name, commands in REQUIRED_CI_COMMANDS.items():
        job = jobs[job_name]
        assert job["name"] == job_name
        assert "if" not in job
        assert "continue-on-error" not in job
        steps = job["steps"]
        assert all("if" not in step and "continue-on-error" not in step for step in steps)
        run_script = "\n".join(step.get("run", "") for step in steps)
        assert all(command in run_script for command in commands)
        for step in steps:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])


def test_container_and_downloaded_tools_are_immutable() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert dockerfile.count("@sha256:") == 3
    assert "GITLEAKS_LINUX_X64_SHA256" in workflow
    assert "sha256sum -c -" in workflow


def test_unenforced_branch_checks_are_recorded_as_release_blocker() -> None:
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")

    assert "GOV-GAP-001" in gaps
    assert "**Status:** OPEN" in gaps
    assert "**Severity:** P0 governance" in gaps
    assert "**Blocks:** R0 and every real-target release" in gaps



def test_agent_delivery_authority_is_explicit_and_fail_closed() -> None:
    rules = (ROOT / ".devin/rules/blackbread.md").read_text(encoding="utf-8")
    skill = (ROOT / ".devin/skills/build-blackbread-agent/SKILL.md").read_text(encoding="utf-8")
    branch_contract = (ROOT / ".github/BRANCH-PROTECTION.md").read_text(encoding="utf-8")
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")

    for content in (rules, skill):
        assert "commit" in content
        assert "push" in content
        assert "merge" in content
        assert "expected head SHA" in content
        assert "blocking debt" in content
        assert "force-push" in content
    assert "Approved automation bypass" in branch_contract
    assert "specific actor" in branch_contract
    assert "repository prose cannot configure a GitHub" in branch_contract
    assert "approved agent bypass" in gaps
    assert "**Status:** OPEN" in gaps

def test_gitleaks_baseline_contains_only_exact_historical_fingerprints() -> None:
    fingerprints = (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
    fingerprint_pattern = re.compile(r"^[0-9a-f]{40}:[A-Za-z0-9_./-]+:[A-Za-z0-9_-]+:[1-9][0-9]*$")

    assert fingerprints
    assert all(fingerprint_pattern.fullmatch(fingerprint) for fingerprint in fingerprints)
