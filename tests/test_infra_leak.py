"""Tests for infrastructure-exposure leak detector.

GitGuardian detects credential-type secrets (API keys, private keys, tokens) but
does NOT detect infrastructure metadata that is equally sensitive for a covert
red-team platform: public IP addresses, SSH usernames, installation paths, SSH
host aliases, and identity file paths. These are OPSEC violations when committed
to a public repository.

The detector scans tracked files (excluding git-ignored local files) for these
patterns and reports violations with file path, line number, and matched text.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from blackbread.security.infra_leak import (
    InfraLeakViolation,
    scan_repository,
)

ROOT = Path(__file__).parents[1]


def test_violation_dataclass_fields() -> None:
    v = InfraLeakViolation(
        file=Path("DEPLOYMENT-STATE.md"),
        line=15,
        pattern="public_ip",
        matched="168.110.192.62",
    )
    assert v.file == Path("DEPLOYMENT-STATE.md")
    assert v.line == 15
    assert v.pattern == "public_ip"
    assert v.matched == "168.110.192.62"


def test_scan_detects_public_ip() -> None:
    content = "HostName: 168.110.192.62\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert len(violations) == 1
    assert violations[0].pattern == "public_ip"
    assert "168.110.192.62" in violations[0].matched


def test_scan_detects_ssh_user() -> None:
    content = "User: ubuntu\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert any(v.pattern == "ssh_user" for v in violations)


def test_scan_detects_identity_file_path() -> None:
    content = "IdentityFile: ~/.ssh/id_oracle_alpha\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert any(v.pattern == "ssh_identity_file" for v in violations)


def test_scan_detects_installation_path() -> None:
    content = "Path: /home/ubuntu/blackbread\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert any(v.pattern == "installation_path" for v in violations)


def test_scan_detects_ssh_alias() -> None:
    content = "ssh oracle-alpha\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert any(v.pattern == "ssh_alias" for v in violations)


def test_scan_ignores_placeholder_values() -> None:
    content = "HostName: <ORACLE_HOST_NAME>\nUser: <ORACLE_USER>\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert violations == []


def test_scan_ignores_localhost_and_private_ips() -> None:
    content = "127.0.0.1\n10.0.0.5\n192.168.1.1\n172.16.0.1\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert violations == []


def test_scan_ignores_test_fixture_content() -> None:
    content = "User: blackbread_test_runtime\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(),
    )
    assert violations == []


def test_allowlist_pattern_suppresses_violation() -> None:
    content = "HostName: 168.110.192.62\n"
    violations = scan_repository(
        files=[("fake/deploy.md", content)],
        allowlist_patterns=(re.compile(r"168\.110"),),
    )
    assert violations == []


def test_scan_repository_on_clean_main_has_no_violations() -> None:
    violations = scan_repository(
        files=None,
        root=ROOT,
        allowlist_patterns=(),
    )
    assert violations == []


def test_scan_excludes_gitignored_files() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "DEPLOYMENT-STATE.local.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "DEPLOYMENT-STATE.local.md must be git-ignored"
