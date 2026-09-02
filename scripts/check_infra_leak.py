"""CI gate: scan tracked files for infrastructure-exposure leaks.

Complements gitleaks (credential secrets) by detecting infrastructure metadata
that GitGuardian/gitleaks do not cover: public IP addresses, SSH usernames,
installation paths, SSH host aliases, and identity file paths.

Exits 1 if any violation is found, 0 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from blackbread.security.infra_leak import scan_repository

ROOT = Path(__file__).parents[1]

ALLOWLIST_PATH = ROOT / ".infra-leak-allowlist"


def _load_allowlist() -> tuple[re.Pattern[str], ...]:
    if not ALLOWLIST_PATH.is_file():
        return ()
    patterns: list[re.Pattern[str]] = []
    for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(re.compile(stripped))
    return tuple(patterns)


def main() -> int:
    allowlist = _load_allowlist()
    violations = scan_repository(
        files=None,
        root=ROOT,
        allowlist_patterns=allowlist,
    )
    if not violations:
        print("No infrastructure-exposure leaks detected.")
        return 0
    print(f"Found {len(violations)} infrastructure-exposure violation(s):")
    for v in violations:
        print(f"  {v.file}:{v.line} [{v.pattern}] {v.matched}")
    print(
        "\nTo suppress a false positive, add the matching regex to "
        ".infra-leak-allowlist (one per line, # for comments)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
