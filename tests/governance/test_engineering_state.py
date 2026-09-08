import subprocess
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from blackbread.governance.engineering_state import (
    EngineeringStateManifest,
    StateTransition,
    TransitionKind,
    build_candidate_manifest,
    check_transition,
    classify_release_bearing_diff,
    render_projection,
    validate_slice_identifier,
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


# Canonical slice identifier grammar (Test F)

VALID_SLICE_IDS = [
    "M1.4c1",
    "M1.4c2a",
    "M1.4b2b-R",
    "M1.4b2c-RECOVERY",
    "M1.4a-FOLLOWUP",
    "M1.3b3b-HARDEN",
    "M1.4",
    "M2.1a3b",
]
INVALID_SLICE_IDS = [
    "M",
    "M1",
    "m1.4c1",
    "M1.4c1 ",
    " M1.4c1",
    "M1.4c1\t",
    "M1.4c1/x",
    "M arbitrary text",
    "M1.4c1-",
    "M1.4c1-r",
    "M1.4c1 R",
    "M1.4c1.extra",
]


@pytest.mark.parametrize("identifier", VALID_SLICE_IDS)
def test_slice_identifier_accepts_canonical_forms(identifier: str):
    assert validate_slice_identifier(identifier) == identifier


@pytest.mark.parametrize("identifier", INVALID_SLICE_IDS)
def test_slice_identifier_rejects_malformed_forms(identifier: str):
    with pytest.raises(ValueError):
        validate_slice_identifier(identifier)


# Exact Markdown projection (Test H)


def test_projection_exact_bytes():
    manifest = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c2a",
        selected_next_slice="M1.4c2b",
    )
    assert render_projection(manifest) == (
        "# BlackBread Engineering State\n"
        "\n"
        "This file records the repository owner's selected work sequence.\n"
        "\n"
        "> [!WARNING]\n"
        "> - on protected main it is the current released-state checkpoint;\n"
        "> - on any feature branch it is only a prospective post-merge projection;\n"
        "> - live GitHub remains the authority for merge, SHA, PR, checks, reviews,\n"
        "    open branches, and release verification;\n"
        "> - GAP-REGISTER.md remains the only authority for gap status.\n"
        "\n"
        "## State metadata\n"
        "\n"
        "* **Current milestone:** M1\n"
        "* **Last released slice:** M1.4c2a\n"
        "* **Selected next slice:** M1.4c2b\n"
        "* **State revision:** 2\n"
    )


# Stale candidate cannot validate against advanced base (Test I)


def test_stale_candidate_fails_against_advanced_base():
    stale = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c2a",
        selected_next_slice="M1.4c2b",
    )
    advanced = EngineeringStateManifest(
        schema_version=1,
        state_revision=2,
        last_released_slice="M1.4c2a",
        selected_next_slice="M1.4c2b",
    )
    transition = StateTransition(
        kind=TransitionKind.RELEASE,
        base_manifest=advanced,
        head_manifest=stale,
        release_bearing_diff=True,
    )
    with pytest.raises(ValueError, match="increment state revision by exactly 1"):
        check_transition(transition)


# Pure candidate construction authority (Test C support)


def _base(rev: int = 1, released: str = "M1.4c1", nxt: str = "M1.4c2a"):
    return EngineeringStateManifest(
        schema_version=1,
        state_revision=rev,
        last_released_slice=released,
        selected_next_slice=nxt,
    )


def test_build_candidate_bootstrap_uses_explicit_arguments():
    c = build_candidate_manifest(None, TransitionKind.BOOTSTRAP, "M1.4b2b-R", "M1.4c2a")
    assert c.last_released_slice == "M1.4b2b-R"
    assert c.selected_next_slice == "M1.4c2a"
    assert c.state_revision == 1


def test_build_candidate_release_promotes_base_selected_slice():
    c = build_candidate_manifest(_base(), TransitionKind.RELEASE, "M1.4c2a", "M1.4c2b")
    assert c.state_revision == 2
    assert c.last_released_slice == "M1.4c2a"
    assert c.selected_next_slice == "M1.4c2b"


def test_build_candidate_release_rejects_wrong_released():
    with pytest.raises(ValueError, match="must promote the base selected slice"):
        build_candidate_manifest(_base(), TransitionKind.RELEASE, "M1.4c2b", "M1.4c2c")


def test_build_candidate_select_preserves_last_released():
    c = build_candidate_manifest(_base(), TransitionKind.SELECT, None, "M1.4c2b")
    assert c.state_revision == 2
    assert c.last_released_slice == "M1.4c1"
    assert c.selected_next_slice == "M1.4c2b"
