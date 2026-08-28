"""Check configured safety-critical module coverage against the blocking threshold."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _coverage_config() -> dict[str, object]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["coverage"]["safety_critical"]


def load_threshold() -> int:
    return int(_coverage_config()["fail_under"])


def load_safety_includes() -> tuple[str, ...]:
    includes = _coverage_config()["include"]
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        raise RuntimeError("safety-critical coverage include must be a list of dotted patterns")
    return tuple(includes)


def _source_directory(include: str) -> Path:
    if not include.startswith("blackbread.") or not include.endswith(".*"):
        raise RuntimeError(f"unsupported safety-critical coverage pattern: {include}")
    module_parts = include.removesuffix(".*").split(".")
    return ROOT / "src" / Path(*module_parts)


def _coverage_pattern(include: str) -> str:
    module_path = include.replace(".", "/").removesuffix("/*")
    return f"*/{module_path}/*"


def safety_files_exist(includes: tuple[str, ...]) -> bool:
    return any(_source_directory(include).is_dir() for include in includes)


def main() -> int:
    includes = load_safety_includes()
    if not safety_files_exist(includes):
        print("No configured safety-critical modules found yet. Skipping blocking check.")
        return 0

    include_patterns = ",".join(_coverage_pattern(include) for include in includes)
    result = subprocess.run(
        [
            "uv",
            "run",
            "coverage",
            "report",
            f"--include={include_patterns}",
            f"--fail-under={load_threshold()}",
        ],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
