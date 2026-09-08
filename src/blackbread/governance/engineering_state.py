from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, field_validator


class EngineeringStateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: StrictInt
    state_revision: StrictInt
    last_released_slice: StrictStr
    selected_next_slice: StrictStr

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError("schema_version must equal 1")
        return v

    @field_validator("state_revision")
    @classmethod
    def validate_state_revision(cls, v: int) -> int:
        if v < 1:
            raise ValueError("state_revision must be a positive integer")
        return v

    @field_validator("selected_next_slice")
    @classmethod
    def validate_selected_next_slice(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("selected_next_slice must be a non-empty string")
        # Ensure it starts with M
        if not v.startswith("M"):
            raise ValueError("slice identifiers must start with M (e.g. M1.4c1)")
        return v

    @field_validator("last_released_slice")
    @classmethod
    def validate_last_released_slice(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("last_released_slice must be a non-empty string")
        if not v.startswith("M"):
            raise ValueError("slice identifiers must start with M (e.g. M1.4c1)")
        return v


class TransitionKind(StrEnum):
    BOOTSTRAP = "bootstrap"
    RELEASE = "release"
    SELECT = "select"
    NO_TRANSITION = "no_transition"


class StateTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: TransitionKind
    base_manifest: EngineeringStateManifest | None
    head_manifest: EngineeringStateManifest
    release_bearing_diff: bool


def _check_bootstrap(transition: StateTransition) -> None:
    if transition.base_manifest is not None:
        raise ValueError("Bootstrap must fail forever after the base contains a manifest")
    head = transition.head_manifest
    if head.schema_version != 1:
        raise ValueError("Bootstrap requires schema version 1")
    if head.state_revision != 1:
        raise ValueError("Bootstrap requires state revision 1")
    if head.last_released_slice != "M1.4c1":
        raise ValueError("Bootstrap requires last released slice M1.4c1")
    if head.selected_next_slice != "M1.4c2a":
        raise ValueError("Bootstrap requires selected next slice M1.4c2a")


def _check_release(transition: StateTransition) -> None:
    head = transition.head_manifest
    base = transition.base_manifest
    if base is None:
        raise ValueError("Non-bootstrap transition requires a base manifest")
    if not transition.release_bearing_diff:
        raise ValueError("Release transition requires a release-bearing diff")
    if head.state_revision != base.state_revision + 1:
        raise ValueError("Release transition must increment state revision by exactly 1")
    if head.last_released_slice != base.selected_next_slice:
        raise ValueError("Release transition must promote the base selected slice to last released")
    if head.selected_next_slice == head.last_released_slice:
        raise ValueError(
            "Release transition must select a new slice, different from the released one"
        )


def _check_select(transition: StateTransition) -> None:
    head = transition.head_manifest
    base = transition.base_manifest
    if base is None:
        raise ValueError("Non-bootstrap transition requires a base manifest")
    if transition.release_bearing_diff:
        raise ValueError("A release-bearing diff may not use select or no-transition semantics")
    if head.state_revision != base.state_revision + 1:
        raise ValueError("Select transition must increment state revision by exactly 1")
    if head.last_released_slice != base.last_released_slice:
        raise ValueError("Select transition cannot change the last released slice")
    if head.selected_next_slice == base.selected_next_slice:
        raise ValueError("Select transition must change the selected next slice")


def _check_no_transition(transition: StateTransition) -> None:
    if transition.base_manifest is None:
        raise ValueError("Non-bootstrap transition requires a base manifest")
    if transition.release_bearing_diff:
        raise ValueError("A release-bearing diff may not use select or no-transition semantics")
    if transition.head_manifest.model_dump() != transition.base_manifest.model_dump():
        raise ValueError("No-transition semantics require identical base and head manifests")


def check_transition(transition: StateTransition) -> None:
    if transition.kind == TransitionKind.BOOTSTRAP:
        _check_bootstrap(transition)
    elif transition.kind == TransitionKind.RELEASE:
        _check_release(transition)
    elif transition.kind == TransitionKind.SELECT:
        _check_select(transition)
    elif transition.kind == TransitionKind.NO_TRANSITION:
        _check_no_transition(transition)
    else:
        raise ValueError(f"Unknown transition kind: {transition.kind}")


def render_projection(manifest: EngineeringStateManifest) -> str:
    milestone = manifest.selected_next_slice.split(".")[0]
    return f"""# BlackBread Engineering State

This file records the repository owner's selected work sequence.

> [!WARNING]
> - on protected main it is the current released-state checkpoint;
> - on any feature branch it is only a prospective post-merge projection;
> - live GitHub remains the authority for merge, SHA, PR, checks, reviews,
    open branches, and release verification;
> - GAP-REGISTER.md remains the only authority for gap status.

## State metadata

* **Current milestone:** {milestone}
* **Last released slice:** {manifest.last_released_slice}
* **Selected next slice:** {manifest.selected_next_slice}
* **State revision:** {manifest.state_revision}
"""


def classify_release_bearing_diff(changed_paths: list[str]) -> bool:
    """
    Classifies a diff as release-bearing if it touches specific paths.
    Normalized to repository-relative POSIX format.
    """
    for path_str in changed_paths:
        path = Path(path_str).as_posix()
        if path.startswith("/") or ".." in path:
            raise ValueError(f"Invalid path traversal or absolute path: {path}")

        # Exact match rules
        if path in {
            "Dockerfile",
            "compose.yml",
            "compose.yaml",
            "pyproject.toml",
            "uv.lock",
            "config/capability-registry.json",
        }:
            return True

        # Prefix rules
        if path.startswith("Dockerfile.") or (
            path.startswith("compose") and (path.endswith(".yml") or path.endswith(".yaml"))
        ):
            return True
        if path.startswith("migrations/") or path.startswith("deploy/"):
            return True

        # src/blackbread exclusion logic
        if path.startswith("src/blackbread/") and not path.startswith("src/blackbread/governance/"):
            return True

    return False
