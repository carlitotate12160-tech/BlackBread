from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from blackbread.governance.size_budget import (
    BudgetConfigurationError,
    QualityCaps,
    cap_increases,
    evaluate_size_budget,
)

ROOT = Path(__file__).parents[1]
CONFIG_PATH = "config/quality-budgets.json"
BOOTSTRAP_CONFIG = json.dumps(
    {
        "schema_version": 1,
        "production_module_max_lines": 400,
        "function_max_lines": 50,
        "test_module_max_lines": 500,
    }
)
GIT_OBJECT_MISSING = 128


class RepositoryReadError(RuntimeError):
    pass


def _run_git(arguments: list[str], *, allow_missing: bool = False) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        try:
            return completed.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryReadError("quality budget input is not UTF-8 text") from exc
    if allow_missing and completed.returncode == GIT_OBJECT_MISSING:
        return None
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    raise RepositoryReadError(f"git {' '.join(arguments)} failed: {stderr}")


def _validate_commit(ref: str) -> None:
    _run_git(["cat-file", "-e", f"{ref}^{{commit}}"])


def _read_file(ref: str, path: str) -> str | None:
    return _run_git(["show", f"{ref}:{path}"], allow_missing=True)


def _read_python_tree(ref: str) -> dict[str, str]:
    listed = _run_git(["ls-tree", "-r", "--name-only", ref, "--", "src/blackbread", "tests"])
    if listed is None:
        raise RepositoryReadError(f"cannot list Python files at {ref}")
    files: dict[str, str] = {}
    for path in listed.splitlines():
        if path.endswith(".py"):
            source = _read_file(ref, path)
            if source is None:
                raise RepositoryReadError(f"listed file is unavailable: {ref}:{path}")
            files[path] = source
    return files


def _resolve_base_ref(explicit: str | None) -> str:
    if explicit:
        return explicit
    configured = os.environ.get("BLACKBREAD_BASE_SHA")
    if configured:
        return configured
    resolved = _run_git(["merge-base", "origin/main", "HEAD"])
    if resolved is None or not resolved.strip():
        raise RepositoryReadError("cannot resolve protected base commit")
    return resolved.strip()


def _caps_for_ref(ref: str, *, bootstrap: bool) -> QualityCaps:
    source = _read_file(ref, CONFIG_PATH)
    if source is not None:
        return QualityCaps.from_json(source)
    if bootstrap:
        return QualityCaps.from_json(BOOTSTRAP_CONFIG)
    raise RepositoryReadError(f"{CONFIG_PATH} is unavailable at {ref}")


def check_repository(base_ref: str, head_ref: str) -> list[str]:
    _validate_commit(base_ref)
    _validate_commit(head_ref)
    base_caps = _caps_for_ref(base_ref, bootstrap=True)
    head_caps = _caps_for_ref(head_ref, bootstrap=False)
    violations = [
        f"quality cap increase is forbidden: {change}"
        for change in cap_increases(base_caps, head_caps)
    ]
    violations.extend(
        evaluate_size_budget(
            _read_python_tree(base_ref),
            _read_python_tree(head_ref),
            head_caps,
        )
    )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref", default="HEAD")
    arguments = parser.parse_args()
    try:
        violations = check_repository(_resolve_base_ref(arguments.base_ref), arguments.head_ref)
    except (BudgetConfigurationError, RepositoryReadError, KeyError, TypeError) as exc:
        print(f"quality budget evaluation failed: {exc}")
        return 2
    if violations:
        print("\n".join(violations))
        return 1
    print("quality size budget passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
