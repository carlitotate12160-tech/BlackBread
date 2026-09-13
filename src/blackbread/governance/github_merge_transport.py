"""HTTPS transport and response parsing for the GitHub merge-evidence collector.

Pinned to the GitHub API host; token in headers only, never embedded in URLs.
All transport types are re-exported from ``github_merge_evidence`` for backward
compatibility.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from email.message import Message
from typing import NamedTuple, Protocol

from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningRequirement,
)

GITHUB_API_BASE = "https://api.github.com"

_KNOWN_RULE_TYPES = frozenset(
    {
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "required_status_checks",
        "code_scanning",
        "pull_request",
        "update",
        "creation",
        "required_signatures",
        "required_deployments",
        "commit_message_pattern",
        "commit_author_email_pattern",
        "committer_email_pattern",
        "branch_name_pattern",
        "tag_name_pattern",
        "workflows",
        "merge_queue",
    }
)


class TransportResult(NamedTuple):
    status: int
    body: object
    next_url: str | None


class TransportError(Exception):
    """Connection-level failure; HTTP errors surface as TransportResult.status."""


class GitHubTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: object | None = None,
    ) -> TransportResult: ...


def _decode_json(payload: bytes) -> object:
    try:
        return json.loads(payload)
    except ValueError:
        return None


def _next_link(headers: Message | None) -> str | None:
    link = headers.get("Link") if headers else None
    if not link:
        return None
    for part in str(link).split(","):
        url, _, rel = part.partition(";")
        if 'rel="next"' in rel:
            return url.strip().strip("<>")
    return None


class UrllibGitHubTransport:
    """HTTPS transport pinned to the GitHub API host; token in headers only."""

    def __init__(self, token: str, base_url: str = GITHUB_API_BASE) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("GitHub API base URL must be an https URL")
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: object | None = None,
    ) -> TransportResult:
        url = path if path.startswith("https://") else f"{self._base_url}{path}"
        if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(self._base_url).netloc:
            raise TransportError(f"refusing non-GitHub host: {urllib.parse.urlsplit(url).netloc}")
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = None if json_body is None else json.dumps(json_body).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310  # nosec B310 -- host is pinned to the GitHub API base URL above
            url, data=data, method=method, headers=self._headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310 -- host is pinned to the GitHub API base URL above
                return TransportResult(
                    response.status, _decode_json(response.read()), _next_link(response.headers)
                )
        except urllib.error.HTTPError as exc:
            return TransportResult(exc.code, _decode_json(exc.read()), _next_link(exc.headers))
        except urllib.error.URLError as exc:
            raise TransportError(f"GitHub API unreachable: {exc.reason}") from exc


def parse_check_run(item: dict[str, object]) -> CheckRunEvidence:
    """Parse one check-run dict into typed evidence; raises on malformed input."""
    raw_id = item["id"]
    if not isinstance(raw_id, int):
        raise ValueError(f"invalid id: {raw_id!r}")
    raw_name = item["name"]
    if not isinstance(raw_name, str):
        raise ValueError(f"invalid name: {raw_name!r}")
    raw_status = item["status"]
    if not isinstance(raw_status, str):
        raise ValueError(f"invalid status: {raw_status!r}")
    raw_conclusion = item.get("conclusion")
    if raw_conclusion is not None and not isinstance(raw_conclusion, str):
        raise ValueError(f"invalid conclusion: {raw_conclusion!r}")
    return CheckRunEvidence(
        check_run_id=raw_id,
        name=raw_name,
        status=raw_status,
        conclusion=raw_conclusion,
    )


class RulesParseError(Exception):
    """Signals malformed rule entry; caller appends to errors and returns None."""


def parse_rules(
    rules: list[object],
) -> tuple[
    tuple[str, ...] | None,
    bool | None,
    tuple[CodeScanningRequirement, ...] | None,
    tuple[str, ...],
]:
    """Parse ruleset rules into normalized fields; raises RulesParseError on malformed input."""
    contexts: tuple[str, ...] | None = None
    strict: bool | None = None
    tools: tuple[CodeScanningRequirement, ...] | None = None
    unknown: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
            raise RulesParseError("malformed rule entry")
        params = rule.get("parameters")
        params = params if isinstance(params, dict) else {}
        rule_type: str = rule["type"]
        if rule_type == "required_status_checks":
            raw = params.get("required_status_checks")
            if isinstance(raw, list) and all(
                isinstance(c, dict) and isinstance(c.get("context"), str) for c in raw
            ):
                contexts = tuple(c["context"] for c in raw)
                strict_val = params.get("strict_required_status_checks_policy")
                strict = strict_val if isinstance(strict_val, bool) else None
        elif rule_type == "code_scanning":
            raw_tools = params.get("code_scanning_tools")
            if isinstance(raw_tools, list):
                parsed_tools = []
                for tool in raw_tools:
                    if not isinstance(tool, dict):
                        continue
                    parsed_tools.append(
                        CodeScanningRequirement(
                            tool=str(tool.get("tool")),
                            security_alerts_threshold=str(tool.get("security_alerts_threshold")),
                            alerts_threshold=str(tool.get("alerts_threshold")),
                        )
                    )
                tools = tuple(parsed_tools)
        elif rule_type not in _KNOWN_RULE_TYPES:
            unknown.append(rule_type)
    return contexts, strict, tools, tuple(unknown)
