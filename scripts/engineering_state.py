import argparse
import os
import subprocess
import sys

from pydantic import ValidationError

from blackbread.governance.engineering_state import (
    EngineeringStateManifest,
    StateTransition,
    TransitionError,
    TransitionKind,
    build_candidate_manifest,
    check_transition,
    classify_release_bearing_diff,
    render_projection,
)

MANIFEST_PATH = ".github/engineering-state.json"
MARKDOWN_PATH = "ENGINEERING-STATE.md"
HISTORY_PATH = "ENGINEERING-HISTORY.md"


class CliError(Exception):
    """Malformed input, unreadable ref, or configuration error (exit 2)."""


class PolicyError(Exception):
    """Transition policy violation or missing required artifact (exit 1)."""


def _validate_commit_ref(ref: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"], capture_output=True, check=False
    )
    if result.returncode != 0:
        raise CliError(f"not a readable commit: {ref}")


def get_git_file(ref: str, path: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "show", f"{ref}:{path}"], stderr=subprocess.DEVNULL
        ).decode("utf-8")
    except subprocess.CalledProcessError:
        return None


def get_changed_files(base_ref: str, head_ref: str) -> list[str]:
    try:
        output = subprocess.check_output(
            ["git", "diff", "--name-only", "--no-renames", f"{base_ref}...{head_ref}"]
        ).decode("utf-8")
        return [line.strip() for line in output.splitlines() if line.strip()]
    except subprocess.CalledProcessError as e:
        raise CliError(f"Error getting diff: {e}") from e


def _read_manifest(ref: str, label: str) -> EngineeringStateManifest | None:
    json_data = get_git_file(ref, MANIFEST_PATH)
    if not json_data:
        return None
    try:
        return EngineeringStateManifest.model_validate_json(json_data)
    except ValidationError as e:
        raise CliError(f"{label} manifest validation error: {e}") from e


def _determine_kind(
    base_manifest: EngineeringStateManifest | None,
    head_manifest: EngineeringStateManifest,
    is_release_bearing: bool,
) -> TransitionKind:
    if base_manifest is None:
        return TransitionKind.BOOTSTRAP
    if is_release_bearing:
        return TransitionKind.RELEASE
    if head_manifest.model_dump() == base_manifest.model_dump():
        return TransitionKind.NO_TRANSITION
    return TransitionKind.SELECT


def _validate_projection(head_manifest: EngineeringStateManifest, head_md: str) -> None:
    expected_md = render_projection(head_manifest)
    if head_md != expected_md:
        raise PolicyError("Candidate markdown does not match deterministic projection")


def _validate_bootstrap_history(base_ref: str, head_ref: str) -> None:
    base_md = get_git_file(base_ref, MARKDOWN_PATH)
    if not base_md:
        return
    head_history = get_git_file(head_ref, HISTORY_PATH)
    if not head_history:
        raise PolicyError("Bootstrap history archive is missing")
    if base_md not in head_history:
        raise PolicyError("Bootstrap history does not contain the exact displaced state")


def do_check(base_ref: str, head_ref: str) -> None:
    _validate_commit_ref(base_ref)
    _validate_commit_ref(head_ref)
    base_manifest = _read_manifest(base_ref, "Base")
    head_manifest = _read_manifest(head_ref, "Candidate")
    if head_manifest is None:
        raise PolicyError("Candidate manifest not found")
    head_md = get_git_file(head_ref, MARKDOWN_PATH)
    if not head_md:
        raise PolicyError("Candidate markdown not found")
    _validate_projection(head_manifest, head_md)
    changed_files = get_changed_files(base_ref, head_ref)
    is_release_bearing = classify_release_bearing_diff(changed_files)
    kind = _determine_kind(base_manifest, head_manifest, is_release_bearing)
    transition = StateTransition(
        kind=kind,
        base_manifest=base_manifest,
        head_manifest=head_manifest,
        release_bearing_diff=is_release_bearing,
    )
    try:
        check_transition(transition)
    except ValueError as e:
        raise PolicyError(f"Transition policy violation: {e}") from e
    if kind == TransitionKind.BOOTSTRAP:
        _validate_bootstrap_history(base_ref, head_ref)


def _validate_transition_args(kind: str, released: str | None) -> TransitionKind:
    try:
        kind_enum = TransitionKind(kind)
    except ValueError as e:
        raise CliError(f"Unknown kind: {kind}") from e
    if kind_enum == TransitionKind.SELECT and released is not None:
        raise CliError("--released is forbidden for select")
    if kind_enum in (TransitionKind.BOOTSTRAP, TransitionKind.RELEASE) and released is None:
        raise CliError(f"--released is required for {kind}")
    return kind_enum


def do_transition(base_ref: str, kind: str, released: str | None, next_slice: str) -> None:
    _validate_commit_ref(base_ref)
    base_json = get_git_file(base_ref, MANIFEST_PATH)
    base_manifest = None
    if base_json:
        try:
            base_manifest = EngineeringStateManifest.model_validate_json(base_json)
        except ValidationError as e:
            raise CliError(f"Base manifest validation error: {e}") from e
    kind_enum = _validate_transition_args(kind, released)
    try:
        candidate = build_candidate_manifest(base_manifest, kind_enum, released, next_slice)
    except TransitionError as e:
        raise PolicyError(str(e)) from e
    except ValidationError as e:
        raise CliError(f"Candidate manifest validation error: {e}") from e
    new_json = candidate.model_dump_json(indent=2)
    new_md = render_projection(candidate)
    _write_state_files(new_json, new_md)


def _write_state_files(json_content: str, md_content: str) -> None:
    """Write both state files. Git commit is the publication boundary."""
    for path, content in (
        (MANIFEST_PATH, json_content + "\n"),
        (MARKDOWN_PATH, md_content),
    ):
        if directory := os.path.dirname(path):
            os.makedirs(directory, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Engineering state CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_cmd = subparsers.add_parser("check")
    check_cmd.add_argument("--base-ref", required=True)
    check_cmd.add_argument("--head-ref", required=True)

    transition_cmd = subparsers.add_parser("transition")
    transition_cmd.add_argument("--base-ref", required=True)
    transition_cmd.add_argument("--kind", required=True, choices=["bootstrap", "release", "select"])
    transition_cmd.add_argument("--released", required=False)
    transition_cmd.add_argument("--next", required=True)

    args = parser.parse_args()
    try:
        if args.command == "check":
            do_check(args.base_ref, args.head_ref)
        elif args.command == "transition":
            do_transition(args.base_ref, args.kind, args.released, args.next)
    except PolicyError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except CliError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
