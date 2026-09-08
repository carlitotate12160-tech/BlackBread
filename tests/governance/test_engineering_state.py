import subprocess
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from blackbread.governance.engineering_state import (
    EngineeringStateManifest,
    StateTransition,
    TransitionKind,
    check_transition,
    classify_release_bearing_diff,
    render_projection,
)


@pytest.fixture
def temp_git_repo():
    with tempfile.TemporaryDirectory() as td:
        repo_dir = Path(td)
        subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
        yield repo_dir


# ---------------------------------------------------------------------------
# Strict manifest schema tests
# ---------------------------------------------------------------------------


def test_manifest_schema_valid():
    manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    assert manifest.schema_version == 1


def test_manifest_schema_rejects_missing_fields():
    with pytest.raises(ValidationError):
        EngineeringStateManifest(schema_version=1, state_revision=1, last_released_slice="M1.4c1")


def test_manifest_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        EngineeringStateManifest(
            schema_version=1,
            state_revision=1,
            last_released_slice="M1.4c1",
            selected_next_slice="M1.4c2a",
            current_branch="foo",
        )


def test_manifest_schema_rejects_boolean_for_integer():
    with pytest.raises(ValidationError):
        EngineeringStateManifest(
            schema_version=True,  # type: ignore
            state_revision=1,
            last_released_slice="M1.4c1",
            selected_next_slice="M1.4c2a",
        )
    with pytest.raises(ValidationError):
        EngineeringStateManifest(
            schema_version=1,
            state_revision=True,  # type: ignore
            last_released_slice="M1.4c1",
            selected_next_slice="M1.4c2a",
        )


def test_manifest_schema_rejects_invalid_schema_version():
    with pytest.raises(ValidationError):
        EngineeringStateManifest(
            schema_version=2,
            state_revision=1,
            last_released_slice="M1.4c1",
            selected_next_slice="M1.4c2a",
        )


def test_manifest_schema_rejects_invalid_revision():
    with pytest.raises(ValidationError):
        EngineeringStateManifest(
            schema_version=1,
            state_revision=0,
            last_released_slice="M1.4c1",
            selected_next_slice="M1.4c2a",
        )


def test_manifest_schema_rejects_invalid_slice_format():
    with pytest.raises(ValidationError):
        EngineeringStateManifest(
            schema_version=1,
            state_revision=1,
            last_released_slice="invalid slice form!",
            selected_next_slice="M1.4c2a",
        )


# ---------------------------------------------------------------------------
# Exact generated view tests
# ---------------------------------------------------------------------------


def test_deterministic_markdown_projection():
    manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    md = render_projection(manifest)
    assert (
        "last_released_slice: M1.4c1" in md or "Last released slice: M1.4c1" in md or "M1.4c1" in md
    )
    assert "M1.4c2a" in md
    assert "on protected main it is the current released-state checkpoint" in md
    assert "GAP-REGISTER.md remains the only authority" in md


# ---------------------------------------------------------------------------
# Transition semantics tests
# ---------------------------------------------------------------------------


def test_bootstrap_transition():
    head_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )

    transition = StateTransition(
        kind=TransitionKind.BOOTSTRAP,
        base_manifest=None,
        head_manifest=head_manifest,
        release_bearing_diff=False,
    )
    check_transition(transition)


def test_bootstrap_fails_if_base_has_manifest():
    base_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    head_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    transition = StateTransition(
        kind=TransitionKind.BOOTSTRAP,
        base_manifest=base_manifest,
        head_manifest=head_manifest,
        release_bearing_diff=False,
    )
    with pytest.raises(
        ValueError, match="Bootstrap must fail forever after the base contains a manifest"
    ):
        check_transition(transition)


def test_release_transition():
    base_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    head_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c2a",
        selected_next_slice="M1.4c2b",
    )
    transition = StateTransition(
        kind=TransitionKind.RELEASE,
        base_manifest=base_manifest,
        head_manifest=head_manifest,
        release_bearing_diff=True,
    )
    check_transition(transition)


def test_release_transition_fails_skipped_slice():
    base_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    head_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c2b",
        selected_next_slice="M1.4c2c",
    )
    transition = StateTransition(
        kind=TransitionKind.RELEASE,
        base_manifest=base_manifest,
        head_manifest=head_manifest,
        release_bearing_diff=True,
    )
    with pytest.raises(ValueError):
        check_transition(transition)


def test_select_transition():
    base_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    head_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2b",
    )
    transition = StateTransition(
        kind=TransitionKind.SELECT,
        base_manifest=base_manifest,
        head_manifest=head_manifest,
        release_bearing_diff=False,
    )
    check_transition(transition)


def test_select_transition_fails_on_release_bearing_diff():
    base_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=1,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2a",
    )
    head_manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c1",
        selected_next_slice="M1.4c2b",
    )
    transition = StateTransition(
        kind=TransitionKind.SELECT,
        base_manifest=base_manifest,
        head_manifest=head_manifest,
        release_bearing_diff=True,
    )
    with pytest.raises(
        ValueError, match="release-bearing diff may not use select or no-transition semantics"
    ):
        check_transition(transition)


# ---------------------------------------------------------------------------
# Release-bearing path classification tests
# ---------------------------------------------------------------------------


def test_release_bearing_path_classification():
    assert classify_release_bearing_diff(["src/blackbread/policy/core.py"]) is True
    assert (
        classify_release_bearing_diff(["src/blackbread/governance/engineering_state.py"]) is False
    )
    assert classify_release_bearing_diff(["migrations/0001_initial.py"]) is True
    assert classify_release_bearing_diff(["config/capability-registry.json"]) is True
    assert classify_release_bearing_diff(["deploy/k8s/deployment.yaml"]) is True
    assert classify_release_bearing_diff(["Dockerfile"]) is True
    assert classify_release_bearing_diff(["compose.yml"]) is True
    assert classify_release_bearing_diff(["pyproject.toml"]) is True
    assert classify_release_bearing_diff(["uv.lock"]) is True
    assert classify_release_bearing_diff(["tests/governance/test_engineering_state.py"]) is False
    assert classify_release_bearing_diff(["README.md"]) is False


# ---------------------------------------------------------------------------
# CI wiring and Makefile checks
# ---------------------------------------------------------------------------


def test_make_and_ci_invoke_engineering_state_check():
    repo_root = Path(__file__).resolve().parent.parent.parent

    ci_yml = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_yml.exists()
    content = ci_yml.read_text()

    assert "scripts/engineering_state.py check" in content
    assert "BLACKBREAD_BASE_SHA" in content
    assert "needs: [quality, tests, security, governance]" in content or (
        "needs:" in content and "governance" in content.split("needs:")[1].split("]")[0]
    )

    makefile = repo_root / "Makefile"
    assert makefile.exists()
    content = makefile.read_text()
    assert "governance" in content
    assert "check:" in content


def test_no_protected_main_writer():
    repo_root = Path(__file__).resolve().parent.parent.parent
    ci_yml = repo_root / ".github" / "workflows" / "ci.yml"
    content = ci_yml.read_text()
    assert "contents: write" not in content
    assert "git push" not in content
