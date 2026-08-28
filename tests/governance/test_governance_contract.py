import json
import re
import tomllib
from pathlib import Path

import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory

from blackbread.health import EXPECTED_SCHEMA_REVISION

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
REQUIRED_CAPABILITY_OWNERS = {
    "scout.passive_asset_intelligence.v1": "Scout",
    "scout.dns_tls_http_observe.v1": "Scout",
    "scout.network_service_observe.v1": "Scout",
    "scout.route_browser_observe.v1": "Scout",
    "scout.public_artifact_secret_detect.v1": "Scout",
    "scout.discovery_signature.v1": "Scout",
    "strike.credential_intelligence_offline.v1": "Strike",
    "strike.authentication_validate.v1": "Strike",
    "strike.authorization_differential.v1": "Strike",
    "strike.service_vulnerability_verify.v1": "Strike",
    "exploit.controlled_proof.v1": "Exploit",
    "post_exploit.objective_read.v1": "Post-Exploit",
    "report.evidence_build.v1": "Report",
}
REQUIRED_CAPABILITY_IDS = set(REQUIRED_CAPABILITY_OWNERS)
REQUIRED_PRD_REQUIREMENT_IDS = {
    "ENG-001",
    "ENG-002",
    "ENG-003",
    "ENG-004",
    "ENG-005",
    "REC-001",
    "REC-002",
    "REC-003",
    "REC-004",
    "REC-005",
    "REC-006",
    "STR-001",
    "STR-002",
    "STR-003",
    "VUL-001",
    "VUL-002",
    "CAP-001",
    "CAP-002",
    "CAP-003",
    "CAP-004",
    "CAP-005",
    "CAP-006",
    "CAP-007",
    "EXP-001",
    "REP-001",
    "REP-002",
    "REP-003",
    "REP-004",
    "REP-005",
    "OPS-001",
    "OPS-002",
    "OPS-003",
    "OPS-004",
    "OPS-005",
    "GOV-001",
    "GOV-002",
    "GOV-003",
    "NFR-001",
    "NFR-002",
    "NFR-003",
    "NFR-004",
    "NFR-005",
    "NFR-006",
    "NFR-007",
    "NFR-008",
    "NFR-009",
    "NFR-010",
    "NFR-011",
}
CANONICAL_REQUIREMENT_STATES = {"DECIDED", "IMPLEMENTED", "VERIFIED", "RELEASED"}
EXPECTED_PRD_REQUIREMENT_STATES = dict.fromkeys(REQUIRED_PRD_REQUIREMENT_IDS, "DECIDED")
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
EXPECTED_RUFF_RULES = {
    "E",
    "W",
    "F",
    "I",
    "B",
    "UP",
    "N",
    "S",
    "ASYNC",
    "C4",
    "RET",
    "SIM",
    "PL",
    "RUF",
    "C90",
}
REQUIRED_CI_COMMANDS = {
    "quality": ("uv run ruff check .", "uv run ruff format --check .", "uv run mypy"),
    "tests": ("uv run pytest", "check_safety_coverage.py"),
    "security": ("uv run bandit", "uv run pip-audit", "./gitleaks git"),
    "governance": ("uv lock --check", "uv run pytest tests/governance --no-cov"),
}


def load_registry() -> dict[str, object]:
    path = ROOT / "config/capability-registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_workflow() -> dict[str, object]:
    path = ROOT / ".github/workflows/ci.yml"
    text = path.read_text(encoding="utf-8")
    quoted = re.sub(r"^on:", '"on":', text, count=1, flags=re.MULTILINE)
    return yaml.safe_load(quoted)


def load_delivery_contract() -> dict[str, object]:
    path = ROOT / ".github/agent-delivery.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_adr_is_accepted_without_claiming_implementation_complete() -> None:
    adr = (ROOT / "ADR-FINAL-002.md").read_text(encoding="utf-8")

    assert "**Status:** Accepted" in adr
    assert "**Implementation status:** M1 trust-spine work in progress" in adr


def test_active_contracts_do_not_inherit_agent_alpha_authority() -> None:
    disclaimer = "Agent-Alpha is historical input only and has no authority over\nBlackBread."
    adr = (ROOT / "ADR-FINAL-002.md").read_text(encoding="utf-8")
    assert disclaimer in adr

    for path in ACTIVE_CONTRACTS:
        content = path.read_text(encoding="utf-8")
        if path.name == "ADR-FINAL-002.md":
            content = content.replace(disclaimer, "")
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
    owners = {capability["id"]: capability["owner_agent"] for capability in capabilities}
    assert set(ids) == REQUIRED_CAPABILITY_IDS
    assert len(ids) == len(set(ids))
    assert owners == REQUIRED_CAPABILITY_OWNERS


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
    requirements = re.findall(r"`([A-Z]+-[0-9]{3})(?: \[([A-Z_]+)\])?`", prd)
    ids = [requirement_id for requirement_id, _ in requirements]
    states = dict(requirements)

    assert set(ids) == REQUIRED_PRD_REQUIREMENT_IDS
    assert len(ids) == len(REQUIRED_PRD_REQUIREMENT_IDS)
    assert all(state in CANONICAL_REQUIREMENT_STATES for _, state in requirements)
    assert states == EXPECTED_PRD_REQUIREMENT_STATES


def test_pyproject_enforces_documented_quality_gates() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff_lint = config["tool"]["ruff"]["lint"]
    ruff_rules = set(ruff_lint["select"])
    dev_dependencies = " ".join(config["dependency-groups"]["dev"])

    assert ruff_rules == EXPECTED_RUFF_RULES
    assert "ignore" not in ruff_lint
    assert "extend-ignore" not in ruff_lint
    assert "extend-per-file-ignores" not in ruff_lint
    assert ruff_lint["per-file-ignores"] == {
        "tests/**": ["S101", "PLR2004"],
        "migrations/**": ["E501"],
        "scripts/**": ["S603", "S607"],
    }
    assert config["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"] == 10
    assert config["tool"]["coverage"]["report"]["fail_under"] == 80
    assert config["tool"]["coverage"]["safety_critical"]["fail_under"] == 90
    safety_include = config["tool"]["coverage"]["safety_critical"]["include"]
    assert "blackbread.policy.*" in safety_include
    assert "blackbread.opsec.*" in safety_include
    assert "blackbread.scope.*" in safety_include
    assert "blackbread.identity.*" in safety_include
    assert "blackbread.ledger.*" in safety_include
    assert "blackbread.security.*" in safety_include
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
    test_job = jobs["tests"]
    postgres = test_job["services"]["postgres"]
    assert "@sha256:" in postgres["image"]
    assert test_job["env"]["BLACKBREAD_TEST_DATABASE_URL"].endswith("/blackbread_test")
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
                uses = step["uses"]
                if uses.startswith("./"):
                    assert (ROOT / uses[2:]).exists()
                else:
                    assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses)


def test_container_and_downloaded_tools_are_immutable() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    gitleaks_path = ROOT / ".github/actions/install-gitleaks/action.yml"
    gitleaks_action = gitleaks_path.read_text(encoding="utf-8")

    assert dockerfile.count("@sha256:") == 3
    assert "GITLEAKS_LINUX_X64_SHA256" in workflow
    assert "postgres:17.11-bookworm@sha256:" in workflow
    assert "postgres:17.11-bookworm@sha256:" in compose
    assert "sha256sum -c -" in gitleaks_action


def test_ci_uses_composite_actions_and_safety_script() -> None:
    assert (ROOT / ".github/actions/setup-uv/action.yml").exists()
    assert (ROOT / ".github/actions/install-gitleaks/action.yml").exists()
    assert (ROOT / "scripts/check_safety_coverage.py").exists()

    setup_uv = (ROOT / ".github/actions/setup-uv/action.yml").read_text(encoding="utf-8")
    assert "actions/setup-python@" in setup_uv
    assert "uv sync --locked --all-groups" in setup_uv
    assert "actions/checkout@" not in setup_uv

    gitleaks = (ROOT / ".github/actions/install-gitleaks/action.yml").read_text(encoding="utf-8")
    assert "sha256sum -c -" in gitleaks

    safety = (ROOT / "scripts/check_safety_coverage.py").read_text(encoding="utf-8")
    assert "SAFETY_MODULES" in safety
    assert "90" in safety


def test_unenforced_branch_checks_are_recorded_as_release_blocker() -> None:
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")

    assert "GOV-GAP-001" in gaps
    assert "**Status:** CLOSED" in gaps
    assert "**Severity:** P0 governance" in gaps
    assert "**Blocks:** R0 and every real-target release" in gaps


def test_agent_delivery_authority_is_explicit_and_fail_closed() -> None:
    contract = load_delivery_contract()
    delivery = contract["agent_delivery"]
    expected = {
        "owner_instruction_required": True,
        "feature_branch_commit_push_allowed": True,
        "pull_request_required": True,
        "direct_push_main_allowed": False,
        "force_push_allowed": False,
        "expected_head_sha_required": True,
        "required_approving_reviews": 1,
        "require_code_owner_review": False,
        "dismiss_stale_reviews": True,
        "require_review_thread_resolution": True,
        "allow_changes_requested": False,
        "require_ai_bot_comment_disposition": True,
        "require_branch_up_to_date": True,
        "required_status_checks": ["governance", "quality", "security", "tests"],
        "allow_blocking_debt": False,
        "ruleset_bypass_actor_type": "Integration",
        "ruleset_bypass_actor_id": 1144995,
        "ruleset_bypass_may_waive_gates": False,
        "ruleset_bypass_scope": "approval_only",
        "ruleset_no_bypass_id": 21644438,
        "ruleset_bypass_id": 21698082,
    }

    assert contract["schema_version"] == 1
    assert delivery == expected

    documents = (
        ROOT / "ADR-FINAL-002.md",
        ROOT / ".devin/rules/blackbread.md",
        ROOT / ".devin/skills/build-blackbread-agent/SKILL.md",
        ROOT / ".github/BRANCH-PROTECTION.md",
    )
    for path in documents:
        content = path.read_text(encoding="utf-8")
        assert "AI-bot comment" in content or "AI review findings" in content
        assert re.search(r"(?:direct push to|push directly to) `main`", content)
        assert "changes requested" in content
        assert "blocking debt" in content or "blocking-debt" in content

    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")
    assert "actor_id: 1144995" in gaps
    assert "21644438" in gaps
    assert "21698082" in gaps
    assert "**Status:** CLOSED" in gaps


def test_runtime_expected_schema_revision_matches_alembic_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == [EXPECTED_SCHEMA_REVISION]


def test_m1_ledger_work_is_honest_about_remaining_r0_blockers() -> None:
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "LEDGER-GAP-001" in gaps
    assert "**Status:** OPEN" in gaps
    assert "**Blocks:** R0 and every target-facing release" in gaps
    assert "R0/M1 is not complete or production-eligible" in readme


def test_gitleaks_baseline_contains_only_exact_historical_fingerprints() -> None:
    content = (ROOT / ".gitleaksignore").read_text(encoding="utf-8")
    fingerprints: list[str] = []
    for line in content.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            fingerprints.append(line)
    fingerprint_pattern = re.compile(r"^[0-9a-f]{40}:[A-Za-z0-9_./-]+:[A-Za-z0-9_-]+:[1-9][0-9]*$")

    assert all(fingerprint_pattern.fullmatch(fingerprint) for fingerprint in fingerprints)

    test_app = (ROOT / "tests/test_app.py").read_text(encoding="utf-8")
    assert "gitleaks:allow" in test_app
