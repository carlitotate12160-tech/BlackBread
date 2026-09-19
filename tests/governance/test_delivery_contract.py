import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
REQUIRED_CI_COMMANDS = {
    "quality": ("uv run ruff check .", "uv run ruff format --check .", "uv run mypy"),
    "tests": ("uv run pytest", "check_safety_coverage.py"),
    "security": ("uv run bandit", "uv run pip-audit", "./gitleaks git", "check_infra_leak.py"),
    "governance": ("uv lock --check", "uv run pytest tests/governance --no-cov"),
}


def load_workflow() -> dict[str, object]:
    path = ROOT / ".github/workflows/ci.yml"
    text = path.read_text(encoding="utf-8")
    quoted = re.sub(r"^on:", '"on":', text, count=1, flags=re.MULTILINE)
    return yaml.safe_load(quoted)


def load_delivery_contract() -> dict[str, object]:
    path = ROOT / ".github/agent-delivery.json"
    return json.loads(path.read_text(encoding="utf-8"))


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
    assert test_job["env"]["BLACKBREAD_TEST_MIGRATION_DATABASE_URL"].endswith("/blackbread_test")
    assert (
        test_job["env"]["BLACKBREAD_TEST_DATABASE_URL"]
        != test_job["env"]["BLACKBREAD_TEST_MIGRATION_DATABASE_URL"]
    )
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
    assert "blackbread_migration" in compose
    assert "blackbread_app" in compose
    assert "blackbread_runtime" not in compose
    assert "init-runtime.sh" in compose
    assert (ROOT / "deploy/postgres/init-runtime.sh").exists()
    migration = (ROOT / "migrations/versions/0002_m1_ledger.py").read_text(encoding="utf-8")
    assert "GRANT SELECT, INSERT ON TABLE agent_events TO blackbread_runtime" in migration
    assert "GRANT UPDATE (ledger_lock_token) ON TABLE engagements" in migration
    assert "SECURITY DEFINER" in migration
    assert "REVOKE ALL ON TABLE clients, engagements, agent_events FROM PUBLIC" in migration
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
    assert "load_safety_includes" in safety
    assert "SAFETY_MODULES" not in safety


def test_ai_review_gate_apparatus_is_fully_removed() -> None:
    removed = (
        ROOT / ".github/workflows/ai-review-gate.yml",
        ROOT / "src/blackbread/governance/ai_review_gate.py",
        ROOT / "docs/AI-REVIEW-SETUP.md",
        ROOT / "tests/governance/test_ai_review_gate.py",
    )
    for path in removed:
        assert not path.exists(), f"withdrawn ai-review-gate artifact still present: {path}"

    delivery = load_delivery_contract()["agent_delivery"]
    assert "pending_required_status_checks" not in delivery
    assert "ai_review_gate_state" not in delivery

    for name in (
        ".devin/rules/blackbread.md",
        ".github/BRANCH-PROTECTION.md",
        ".github/agent-delivery.json",
        "AGENTS.md",
        "ENGINEERING-STATE.md",
    ):
        content = (ROOT / name).read_text(encoding="utf-8")
        assert "ai-review-gate" not in content, (
            f"{name} still references the removed ai-review-gate"
        )


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
        "required_approving_reviews": 0,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "require_extra_approval_for_unattributed_changes": False,
        "dismiss_stale_reviews": True,
        "require_review_thread_resolution": True,
        "allow_changes_requested": False,
        "require_ai_bot_comment_disposition": False,
        "require_branch_up_to_date": True,
        "required_status_checks": [
            {"context": "ci-ok", "integration_id": 15368},
            {"context": "GitGuardian Security Checks", "integration_id": 46505},
        ],
        "required_code_scanning": [
            {
                "tool": "CodeQL",
                "security_alerts_threshold": "high_or_higher",
                "alerts_threshold": "errors",
            }
        ],
        "allow_blocking_debt": False,
        "ruleset_id": 21644438,
    }

    assert contract["schema_version"] == 3
    assert delivery == expected

    required_checks = {check["context"] for check in delivery["required_status_checks"]}
    assert required_checks == {"ci-ok", "GitGuardian Security Checks"}
    assert "CodeQL" not in required_checks
    assert "ai-review-gate" not in required_checks
    assert "Sourcery review" not in required_checks
    assert "pending_required_status_checks" not in delivery

    delivery_rules = (ROOT / ".devin/rules/blackbread.md").read_text(encoding="utf-8")
    branch_protection = (ROOT / ".github/BRANCH-PROTECTION.md").read_text(encoding="utf-8")
    for content in (delivery_rules, branch_protection):
        assert "mandatory first-party CI" in content
        assert "PR-Agent" in content
        assert "CodeRabbit" in content

    documents = (
        ROOT / "ADR-FINAL-002.md",
        ROOT / ".devin/rules/blackbread.md",
        ROOT / ".github/BRANCH-PROTECTION.md",
    )
    for path in documents:
        content = path.read_text(encoding="utf-8")
        assert "AI-bot comment" in content or "AI review findings" in content
        assert re.search(r"(?:direct push to|push directly to) `main`", content)
        assert "changes requested" in content
        assert "blocking debt" in content or "blocking-debt" in content

    build_agent_skill = (
        ROOT / ".devin/skills/build-blackbread-agent/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "[blackbread-engineering](../blackbread-engineering/SKILL.md)" in build_agent_skill
    assert "does not define a separate merge or bypass procedure" in build_agent_skill
    assert "final merge workflow" not in build_agent_skill
    assert "automation-integration bypass" not in build_agent_skill

    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")
    assert "21644438" in gaps
    assert "21698082" in gaps
    governance_gap = gaps.split("## GOV-GAP-001", maxsplit=1)[1].split(
        "## LEDGER-GAP-001", maxsplit=1
    )[0]
    assert "**Status:** CLOSED" in governance_gap

    assert delivery["require_review_thread_resolution"] is True

    test_audit = (ROOT / "TEST-AUDIT.md").read_text(encoding="utf-8")
    codeowners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    assert "CodeRabbit auto-review" not in test_audit
    assert "CodeRabbit AI review runs in parallel" not in codeowners


def test_solo_developer_governance_documents_match_machine_contract() -> None:
    delivery = load_delivery_contract()["agent_delivery"]
    delivery_rules = (ROOT / ".devin/rules/blackbread.md").read_text(encoding="utf-8")
    branch_protection = (ROOT / ".github/BRANCH-PROTECTION.md").read_text(encoding="utf-8")
    gaps = (ROOT / "GAP-REGISTER.md").read_text(encoding="utf-8")

    assert delivery["require_extra_approval_for_unattributed_changes"] is False
    assert "require_extra_approval_for_unattributed_changes` is disabled" in delivery_rules
    assert "human Code Owner approval gate" not in branch_protection
    assert "kept in `evaluate` mode" not in branch_protection
    assert "is disabled as rollback evidence" in branch_protection
    assert "`main-approval-required` ruleset (`21698082`) is disabled" in gaps
