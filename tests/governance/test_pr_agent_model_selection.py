from pathlib import Path

from blackbread.governance.safety_paths import paths_require_binding_review

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/pr-agent.yml"


def test_safety_critical_paths_require_binding_review() -> None:
    assert paths_require_binding_review(["src/blackbread/ledger/hashing.py"])
    assert paths_require_binding_review(["docs/design.md", "src/blackbread/graph/domain.py"])
    assert not paths_require_binding_review(["docs/design.md", "README.md"])


def test_path_classification_is_segment_aware() -> None:
    assert not paths_require_binding_review(["src/blackbread/ledgerish/parser.py"])
    assert not paths_require_binding_review(["config/capability-registry.json.backup"])


def test_pr_agent_workflow_fails_closed_and_matches_label_exactly() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "set -euo pipefail" in workflow
    assert 'gh pr diff "$PR_NUMBER" --name-only' in workflow
    assert "paths_require_binding_review" in workflow
    assert '.labels[].name == "safety-critical"' in workflow
    assert '|| echo ""' not in workflow
    assert 'grep -qi "safety-critical"' not in workflow


def test_critical_path_without_label_cannot_run_advisory_review() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'if [[ "$PATH_REQUIRES_BINDING" == "true" && "$HAS_LABEL" != "true" ]]' in workflow
    assert "Safety-critical changed path requires the safety-critical label" in workflow
    assert "exit 1" in workflow


def test_binding_review_has_no_advisory_model_fallback() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "echo 'fallback_models=[]'" in workflow
    assert "steps.select_model.outputs.fallback_models" in workflow
    assert "fallback=deepseek/deepseek-v4-flash" not in workflow
