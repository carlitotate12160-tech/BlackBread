import argparse
import subprocess
import sys

from pydantic import ValidationError

from blackbread.governance.engineering_state import (
    EngineeringStateManifest,
    StateTransition,
    TransitionKind,
    check_transition,
    classify_release_bearing_diff,
    render_projection,
)

MANIFEST_PATH = ".github/engineering-state.json"
MARKDOWN_PATH = "ENGINEERING-STATE.md"
HISTORY_PATH = "ENGINEERING-HISTORY.md"


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
            ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"]
        ).decode("utf-8")
        return [line.strip() for line in output.splitlines() if line.strip()]
    except subprocess.CalledProcessError as e:
        print(f"Error getting diff: {e}", file=sys.stderr)
        sys.exit(2)


def _read_manifest(ref: str, kind: str) -> EngineeringStateManifest | None:
    json_data = get_git_file(ref, MANIFEST_PATH)
    if not json_data:
        return None
    try:
        return EngineeringStateManifest.model_validate_json(json_data)
    except ValidationError as e:
        print(f"{kind} manifest validation error: {e}", file=sys.stderr)
        sys.exit(2 if kind == "Base" else 1)


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


def do_check(base_ref: str, head_ref: str) -> None:
    base_manifest = _read_manifest(base_ref, "Base")
    head_manifest = _read_manifest(head_ref, "Candidate")

    if head_manifest is None:
        print("Candidate manifest not found", file=sys.stderr)
        sys.exit(1)

    # Check Markdown
    head_md = get_git_file(head_ref, MARKDOWN_PATH)
    if not head_md:
        print("Candidate markdown not found", file=sys.stderr)
        sys.exit(1)

    expected_md = render_projection(head_manifest)
    if head_md != expected_md:
        print("Candidate markdown does not match deterministic projection", file=sys.stderr)
        sys.exit(1)

    # Classify diff
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
        print(f"Transition policy violation: {e}", file=sys.stderr)
        sys.exit(1)

    # Extra check for bootstrap history
    if kind == TransitionKind.BOOTSTRAP:
        head_history = get_git_file(head_ref, HISTORY_PATH)
        base_md = get_git_file(base_ref, MARKDOWN_PATH)
        if base_md and head_history and base_md not in head_history:
            print("Bootstrap history does not contain the old narrative", file=sys.stderr)
            sys.exit(1)


def do_transition(base_ref: str, kind: str, released: str | None, next_slice: str) -> None:
    base_json = get_git_file(base_ref, MANIFEST_PATH)
    base_manifest = None
    if base_json:
        base_manifest = EngineeringStateManifest.model_validate_json(base_json)

    if kind == "bootstrap":
        head_manifest = EngineeringStateManifest(
            schema_version=1,
            state_revision=1,
            last_released_slice="M1.4c1",
            selected_next_slice="M1.4c2a",
        )
    elif kind == "release":
        if not base_manifest:
            print("Cannot transition release without base manifest", file=sys.stderr)
            sys.exit(2)
        if not released:
            print("--released is required for release transition", file=sys.stderr)
            sys.exit(2)
        head_manifest = EngineeringStateManifest(
            schema_version=1,
            state_revision=base_manifest.state_revision + 1,
            last_released_slice=released,
            selected_next_slice=next_slice,
        )
    elif kind == "select":
        if not base_manifest:
            print("Cannot transition select without base manifest", file=sys.stderr)
            sys.exit(2)
        head_manifest = EngineeringStateManifest(
            schema_version=1,
            state_revision=base_manifest.state_revision + 1,
            last_released_slice=base_manifest.last_released_slice,
            selected_next_slice=next_slice,
        )
    else:
        print(f"Unknown kind {kind}", file=sys.stderr)
        sys.exit(2)

    new_json = head_manifest.model_dump_json(indent=2)
    new_md = render_projection(head_manifest)

    # Atomic-like write for valid command
    with open(MANIFEST_PATH, "w") as f:
        f.write(new_json)
        f.write("\n")
    with open(MARKDOWN_PATH, "w") as f:
        f.write(new_md)


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

    if args.command == "check":
        do_check(args.base_ref, args.head_ref)
    elif args.command == "transition":
        do_transition(args.base_ref, args.kind, args.released, args.next)


if __name__ == "__main__":
    main()
