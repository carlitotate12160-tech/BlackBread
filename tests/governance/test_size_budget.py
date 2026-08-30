import json
import re
from pathlib import Path

import yaml

from blackbread.governance.size_budget import QualityCaps, cap_increases, evaluate_size_budget

ROOT = Path(__file__).parents[2]


def _lines(count: int) -> str:
    return "\n".join(f"line_{index}" for index in range(count))


def test_quality_caps_cannot_increase_from_protected_base() -> None:
    base = QualityCaps(production_module=400, function=50, test_module=500)
    head = QualityCaps(production_module=401, function=51, test_module=501)

    assert cap_increases(base, head) == [
        "production_module: 400 -> 401",
        "function: 50 -> 51",
        "test_module: 500 -> 501",
    ]


def test_quality_caps_may_decrease() -> None:
    base = QualityCaps(production_module=400, function=50, test_module=500)
    head = QualityCaps(production_module=350, function=45, test_module=450)

    assert cap_increases(base, head) == []


def test_legacy_oversized_test_module_may_shrink() -> None:
    caps = QualityCaps(production_module=400, function=50, test_module=500)
    base_files = {"tests/ledger/test_ledger.py": _lines(563)}
    head_files = {"tests/ledger/test_ledger.py": _lines(540)}

    assert evaluate_size_budget(base_files, head_files, caps) == []


def test_legacy_oversized_test_module_cannot_grow() -> None:
    caps = QualityCaps(production_module=400, function=50, test_module=500)
    base_files = {"tests/governance/test_contract.py": _lines(537)}
    head_files = {"tests/governance/test_contract.py": _lines(541)}

    assert evaluate_size_budget(base_files, head_files, caps) == [
        "tests/governance/test_contract.py: 541 lines exceeds protected allowance 537"
    ]


def test_new_test_module_cannot_create_an_oversize_exception() -> None:
    caps = QualityCaps(production_module=400, function=50, test_module=500)
    head_files = {"tests/governance/test_new_policy.py": _lines(501)}

    assert evaluate_size_budget({}, head_files, caps) == [
        "tests/governance/test_new_policy.py: 501 lines exceeds protected allowance 500"
    ]


def test_renamed_legacy_module_is_treated_as_new() -> None:
    caps = QualityCaps(production_module=400, function=50, test_module=500)
    base_files = {"tests/ledger/test_old.py": _lines(563)}
    head_files = {"tests/ledger/test_renamed.py": _lines(563)}

    assert evaluate_size_budget(base_files, head_files, caps) == [
        "tests/ledger/test_renamed.py: 563 lines exceeds protected allowance 500"
    ]


def test_legacy_oversized_function_cannot_grow() -> None:
    caps = QualityCaps(production_module=400, function=3, test_module=500)
    base_files = {"src/blackbread/example.py": "def existing():\n    one = 1\n    return one\n"}
    head_files = {
        "src/blackbread/example.py": (
            "def existing():\n    one = 1\n    two = 2\n    return one + two\n"
        )
    }

    assert evaluate_size_budget(base_files, head_files, caps) == [
        "src/blackbread/example.py:existing: 4 lines exceeds protected allowance 3"
    ]


def test_legacy_oversized_function_may_remain_unchanged() -> None:
    caps = QualityCaps(production_module=400, function=3, test_module=500)
    source = "def existing():\n    one = 1\n    two = 2\n    return one + two\n"
    files = {"src/blackbread/example.py": source}

    assert evaluate_size_budget(files, files, caps) == []


def test_new_duplicate_function_does_not_reuse_legacy_allowance() -> None:
    caps = QualityCaps(production_module=400, function=3, test_module=500)
    base = "def repeated():\n    one = 1\n    two = 2\n    return one + two\n"
    head = base + "\n\ndef repeated():\n    one = 1\n    two = 2\n    return one + two\n"

    assert evaluate_size_budget(
        {"src/blackbread/example.py": base},
        {"src/blackbread/example.py": head},
        caps,
    ) == ["src/blackbread/example.py:repeated#2: 4 lines exceeds protected allowance 3"]


def test_unchanged_legacy_duplicate_functions_keep_distinct_allowances() -> None:
    caps = QualityCaps(production_module=400, function=3, test_module=500)
    source = (
        "def repeated():\n    one = 1\n    two = 2\n    return one + two\n"
        "\n\ndef repeated():\n    three = 3\n    four = 4\n    return three + four\n"
    )
    files = {"src/blackbread/example.py": source}

    assert evaluate_size_budget(files, files, caps) == []


def test_unrelated_duplicate_cannot_take_original_allowance() -> None:
    caps = QualityCaps(production_module=400, function=3, test_module=500)
    base = "def repeated():\n    one = 1\n    two = 2\n    return one + two\n"
    head = f"def repeated():\n    wrong = 1\n    code = 2\n    return wrong - code\n\n\n{base}"

    assert evaluate_size_budget(
        {"src/blackbread/example.py": base},
        {"src/blackbread/example.py": head},
        caps,
    ) == ["src/blackbread/example.py:repeated#1: 4 lines exceeds protected allowance 3"]


def test_legacy_function_allowance_does_not_move_between_scopes() -> None:
    caps = QualityCaps(production_module=400, function=3, test_module=500)
    base = "def repeated():\n    one = 1\n    two = 2\n    return one + two\n"
    head = (
        "class Container:\n"
        "    def repeated():\n"
        "        one = 1\n"
        "        two = 2\n"
        "        return one + two\n"
    )

    assert evaluate_size_budget(
        {"src/blackbread/example.py": base},
        {"src/blackbread/example.py": head},
        caps,
    ) == ["src/blackbread/example.py:Container.repeated: 4 lines exceeds protected allowance 3"]


def test_unique_scoped_legacy_function_may_remain_unchanged() -> None:
    caps = QualityCaps(production_module=400, function=3, test_module=500)
    source = (
        "class Container:\n"
        "    def existing():\n"
        "        one = 1\n"
        "        two = 2\n"
        "        return one + two\n"
    )
    files = {"src/blackbread/example.py": source}

    assert evaluate_size_budget(files, files, caps) == []


def _workflow(path: str) -> dict[str, object]:
    source = (ROOT / path).read_text(encoding="utf-8")
    quoted = re.sub(r"^on:", '"on":', source, count=1, flags=re.MULTILINE)
    return yaml.safe_load(quoted)


def test_quality_budget_configuration_keeps_existing_caps() -> None:
    configured = json.loads((ROOT / "config/quality-budgets.json").read_text(encoding="utf-8"))

    assert configured == {
        "schema_version": 1,
        "production_module_max_lines": 400,
        "function_max_lines": 50,
        "test_module_max_lines": 500,
    }


def test_governance_job_evaluates_size_budget_against_event_base() -> None:
    workflow = _workflow(".github/workflows/ci.yml")
    steps = workflow["jobs"]["governance"]["steps"]
    checkout = steps[0]
    budget_step = next(
        step for step in steps if step.get("name") == "Enforce protected size budget"
    )

    assert checkout["with"]["fetch-depth"] == 0
    assert "pull_request.base.sha" in budget_step["env"]["BLACKBREAD_BASE_SHA"]
    assert budget_step["run"] == "uv run python scripts/check_size_budget.py"


def test_protected_workflow_never_executes_pull_request_code() -> None:
    workflow = _workflow(".github/workflows/quality-budget.yml")
    job = workflow["jobs"]["quality-budget"]
    steps = job["steps"]
    checkout = steps[0]
    evaluation = steps[1]

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"pull_request_target"}
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert evaluation["env"]["PYTHONPATH"] == "src"
    assert "pull/${PR_NUMBER}/head:refs/remotes/origin/pr-head" in evaluation["run"]
    assert "python scripts/check_size_budget.py" in evaluation["run"]
    assert "secrets." not in (ROOT / ".github/workflows/quality-budget.yml").read_text(
        encoding="utf-8"
    )
