"""Check safety-critical module coverage against the 90% threshold.

Reads the safety-critical module patterns from pyproject.toml
([tool.coverage.safety_critical]) and runs `coverage report` with
--include and --fail-under. Exits 0 if no safety-critical modules
exist yet, or if coverage meets the threshold.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
SAFETY_MODULES = ("policy", "opsec", "scope", "identity", "ledger", "security")


def safety_files_exist() -> bool:
    src = ROOT / "src" / "blackbread"
    if not src.exists():
        return False
    return any((src / mod).is_dir() for mod in SAFETY_MODULES)


def load_threshold() -> int:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return int(config["tool"]["coverage"]["safety_critical"]["fail_under"])


def main() -> int:
    if not safety_files_exist():
        print("No safety-critical modules found yet. Skipping 90% check.")
        return 0

    threshold = load_threshold()
    include_patterns = ",".join(f"blackbread.{mod}.*" for mod in SAFETY_MODULES)

    result = subprocess.run(
        [
            "uv",
            "run",
            "coverage",
            "report",
            f"--include={include_patterns}",
            f"--fail-under={threshold}",
        ],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
