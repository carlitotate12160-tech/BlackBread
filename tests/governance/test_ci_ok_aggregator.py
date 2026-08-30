"""Governance tests for the ci-ok aggregator job.

Extracted from test_governance_contract.py to avoid expanding an
already oversized test module (AGENTS.md: do not add new scenarios to
an oversized test module without first splitting it by behavior).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
REQUIRED_CI_COMMANDS = {
    "quality": ("uv run ruff check .", "uv run ruff format --check .", "uv run mypy"),
    "tests": ("uv run pytest", "check_safety_coverage.py"),
    "security": ("uv run bandit", "uv run pip-audit", "./gitleaks git"),
    "governance": ("uv lock --check", "uv run pytest tests/governance --no-cov"),
}


def _load_workflow() -> dict[str, object]:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    text = path.read_text(encoding="utf-8")
    quoted = re.sub(r"^on:", '"on":', text, count=1, flags=re.MULTILINE)
    loaded = yaml.safe_load(quoted)
    assert isinstance(loaded, dict)
    return loaded


def test_ci_ok_aggregator_exists_and_uses_always() -> None:
    """ci-ok must exist and use `if: always()` aggregator pattern."""
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    assert "ci-ok" in jobs, "ci-ok aggregator job must exist"
    ci_ok = jobs["ci-ok"]
    assert ci_ok["if"] == "always()", "ci-ok must use if: always() aggregator pattern"


def test_ci_ok_needs_all_required_ci_jobs() -> None:
    """ci-ok must aggregate every required first-party CI job in its needs list."""
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    ci_ok = jobs["ci-ok"]
    assert set(ci_ok["needs"]) == set(REQUIRED_CI_COMMANDS.keys()), (
        "ci-ok must aggregate all required CI jobs"
    )


def test_ci_ok_fails_on_non_success_results() -> None:
    """ci-ok must fail when any needed job is not `success` (fail, cancel, skip)."""
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    assert "ci-ok" in jobs
    ci_ok = jobs["ci-ok"]
    steps = ci_ok["steps"]
    run_script = "\n".join(step.get("run", "") for step in steps)
    assert "success" in run_script, "ci-ok must check for success result"
    assert '!= "success"' in run_script, "ci-ok must reject non-success results"
