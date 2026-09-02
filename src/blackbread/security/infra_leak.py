"""Infrastructure-exposure leak detector.

GitGuardian detects credential-type secrets (API keys, private keys, tokens) but
does not detect infrastructure metadata that is equally sensitive for a covert
red-team platform: public IP addresses, SSH usernames, installation paths, SSH
host aliases, and identity file paths.

This module scans tracked files for these patterns and reports violations. It is
intended to run as a CI gate alongside gitleaks, bandit, and pip-audit.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PRIVATE_IP_PATTERNS = (
    re.compile(r"^127\."),
    re.compile(r"^10\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[01])\."),
    re.compile(r"^0\.0\.0\.0"),
)

TEST_NET_PATTERNS = (
    re.compile(r"^192\.0\.2\."),
    re.compile(r"^198\.51\.100\."),
    re.compile(r"^203\.0\.113\."),
)

PLACEHOLDER_PATTERNS = (
    re.compile(r"<[^>]+>"),
    re.compile(r"\$\{[^}]+\}"),
)

TEST_USER_PATTERNS = (
    re.compile(r"blackbread_test_\w+"),
    re.compile(r"blackbread_\w+"),
)

DETECTOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "public_ip": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
    ),
    "ssh_user": re.compile(r"(?i)\bUser:\s+(\w+)"),
    "ssh_identity_file": re.compile(r"(?i)IdentityFile:\s+(~?/[\w/.-]+)"),
    "installation_path": re.compile(r"(?i)Path:\s+(/(?:home|opt|srv|var|root)/[\w/-]+)"),
    "ssh_alias": re.compile(r"(?i)\bssh\s+([a-z][\w-]*)"),
}

SSH_USER_ALLOWLIST = frozenset({"root", "admin", "user", "test", "ci", "runner", "deploy", "git"})

SSH_ALIAS_ALLOWLIST = frozenset(
    {
        "localhost",
        "host",
        "example",
        "test",
        "ci",
        "ke",
        "config",
        "alias",
        "to",
        "via",
        "port",
        "key",
        "session",
        "connection",
        "access",
        "tunnel",
        "proxy",
        "server",
        "client",
        "service",
    }
)

SELF_EXCLUSION_PREFIXES = (
    "src/blackbread/security/",
    "tests/test_infra_leak.py",
    "scripts/check_infra_leak.py",
)


@dataclass(frozen=True)
class InfraLeakViolation:
    file: Path
    line: int
    pattern: str
    matched: str


def _is_private_or_test_ip(ip: str) -> bool:
    if any(pat.match(ip) for pat in PRIVATE_IP_PATTERNS):
        return True
    return any(pat.match(ip) for pat in TEST_NET_PATTERNS)


def _is_placeholder(value: str) -> bool:
    return any(pat.search(value) for pat in PLACEHOLDER_PATTERNS)


def _is_test_user(value: str) -> bool:
    return any(pat.search(value) for pat in TEST_USER_PATTERNS)


def _is_allowlisted(value: str, allowlist: frozenset[str]) -> bool:
    return value.lower() in allowlist


def _should_skip_match(
    pattern_name: str,
    matched_text: str,
    captured: str,
    allowlist_patterns: tuple[re.Pattern[str], ...],
) -> bool:
    if any(ap.search(matched_text) for ap in allowlist_patterns):
        return True
    if _is_placeholder(captured):
        return True
    if pattern_name == "public_ip":
        return _is_private_or_test_ip(matched_text)
    if pattern_name == "ssh_user":
        return _is_allowlisted(captured, SSH_USER_ALLOWLIST) or _is_test_user(captured)
    if pattern_name == "ssh_alias":
        return _is_allowlisted(captured, SSH_ALIAS_ALLOWLIST)
    return False


def _check_line(
    file_path: Path,
    line_no: int,
    line: str,
    allowlist_patterns: tuple[re.Pattern[str], ...],
) -> list[InfraLeakViolation]:
    violations: list[InfraLeakViolation] = []
    for pattern_name, regex in DETECTOR_PATTERNS.items():
        for match in regex.finditer(line):
            matched_text = match.group(0)
            captured = match.group(1) if match.groups() else matched_text
            if _should_skip_match(pattern_name, matched_text, captured, allowlist_patterns):
                continue
            violations.append(
                InfraLeakViolation(
                    file=file_path, line=line_no, pattern=pattern_name, matched=matched_text
                )
            )
    return violations


def _list_tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def scan_repository(
    files: list[tuple[str, str]] | None,
    root: Path | None = None,
    allowlist_patterns: tuple[re.Pattern[str], ...] = (),
) -> list[InfraLeakViolation]:
    if files is not None:
        all_violations: list[InfraLeakViolation] = []
        for file_str, content in files:
            file_path = Path(file_str)
            for line_no, line in enumerate(content.splitlines(), start=1):
                all_violations.extend(_check_line(file_path, line_no, line, allowlist_patterns))
        return all_violations

    if root is None:
        raise ValueError("root is required when files is None")

    tracked = _list_tracked_files(root)
    violations: list[InfraLeakViolation] = []
    for rel in tracked:
        if any(rel.startswith(prefix) for prefix in SELF_EXCLUSION_PREFIXES):
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(content.splitlines(), start=1):
            violations.extend(_check_line(Path(rel), line_no, line, allowlist_patterns))
    return violations
