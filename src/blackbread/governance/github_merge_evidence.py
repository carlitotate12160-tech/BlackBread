"""Read-only GitHub evidence collector and merge-readiness module CLI.

Binds one pull request's ruleset, check-run, code-scanning, review, and
identity evidence into an immutable :class:`EvidenceSnapshot`, then hands it
to the pure evaluator. Read-only: it performs GET requests and one GraphQL
query; it cannot mutate the repository, trigger workflows, or merge. The
token is read from the environment and never printed or embedded in URLs.
"""

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from blackbread.governance.github_merge_transport import (
    GITHUB_API_BASE,
    GitHubTransport,
    RulesParseError,
    TransportError,
    TransportResult,
    UrllibGitHubTransport,
    parse_check_run,
    parse_rules,
)
from blackbread.governance.merge_readiness import (
    CheckRunEvidence,
    CodeScanningAlertEvidence,
    CodeScanningAnalysisEvidence,
    CodeScanningRequirement,
    DeliveryContract,
    EvidenceSnapshot,
    PullRequestIdentity,
    ReadinessReport,
    RulesetEvidence,
    evaluate_readiness,
)

_HTTP_OK = 200
_CONTRACT_SCHEMA_VERSION = 3
_MAX_PAGES = 20
_PULL_REQUEST_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
    "pullRequest(number:$number){headRefOid baseRefOid potentialMergeCommit{oid} "
    "mergeStateStatus reviewDecision reviewThreads(first:100){nodes{isResolved} "
    "pageInfo{hasNextPage}}}}}"
)

__all__ = [
    "GITHUB_API_BASE",
    "GitHubTransport",
    "MergeEvidenceCollector",
    "RulesParseError",
    "TransportError",
    "TransportResult",
    "UrllibGitHubTransport",
    "main",
    "parse_check_run",
    "parse_rules",
]


class _PullRequestRead(NamedTuple):
    identity: PullRequestIdentity
    merge_state_status: str | None
    unresolved_review_threads: int | None
    changes_requested: bool | None


def _count_unresolved_threads(threads: object, errors: list[str]) -> int | None:
    """Count unresolved review threads; None if unreadable or paginated."""
    if not (
        isinstance(threads, dict)
        and isinstance(threads.get("nodes"), list)
        and isinstance(threads.get("pageInfo"), dict)
    ):
        return None
    if threads["pageInfo"].get("hasNextPage"):
        errors.append("pull_request: review-thread pagination exceeded")
        return None
    return sum(
        1 for node in threads["nodes"] if isinstance(node, dict) and node.get("isResolved") is False
    )


class MergeEvidenceCollector:
    """Collects one read-only evidence snapshot bound to a pull request."""

    def __init__(self, transport: GitHubTransport, repository: str) -> None:
        owner, separator, name = repository.partition("/")
        if not separator or not owner or not name or "/" in name:
            raise ValueError(f"repository must be 'owner/name': {repository!r}")
        self._transport = transport
        self._repository = repository
        self._owner = owner
        self._name = name

    def collect(self, pr_number: int, contract: DeliveryContract) -> EvidenceSnapshot:
        errors: list[str] = []
        ruleset = self._ruleset(contract.ruleset_id, errors)
        before = self._pull_request(pr_number, errors)
        head_sha = before.identity.head_sha if before else None
        check_runs = self._check_runs(head_sha, errors)
        analyses = self._analyses(pr_number, errors)
        alerts = self._alerts(pr_number, contract, errors)
        after = self._pull_request(pr_number, errors)
        return EvidenceSnapshot(
            repository=self._repository,
            ruleset=ruleset,
            pull_request_before=before.identity if before else None,
            pull_request_after=after.identity if after else None,
            merge_state_status=after.merge_state_status if after else None,
            unresolved_review_threads=after.unresolved_review_threads if after else None,
            changes_requested=after.changes_requested if after else None,
            check_runs=check_runs,
            analyses=analyses,
            alerts=alerts,
            errors=tuple(errors),
        )

    def _paginate(
        self,
        path: str,
        params: Mapping[str, str] | None,
        items_key: str | None,
        errors: list[str],
        source: str,
    ) -> list[dict[str, object]] | None:
        items: list[dict[str, object]] = []
        url: str | None = path
        query = params
        for _ in range(_MAX_PAGES):
            if url is None:
                return items
            try:
                result = self._transport.request("GET", url, params=query)
            except TransportError as exc:
                errors.append(f"{source}: {exc}")
                return None
            page: object = (
                (None if not isinstance(result.body, dict) else result.body.get(items_key))
                if items_key
                else result.body
            )
            if result.status != _HTTP_OK or not isinstance(page, list):
                errors.append(f"{source}: HTTP {result.status}")
                return None
            if not all(isinstance(item, dict) for item in page):
                errors.append(f"{source}: malformed page")
                return None
            items.extend(page)
            url = result.next_url
            query = None
        errors.append(f"{source}: pagination limit {_MAX_PAGES} pages exceeded")
        return None

    def _ruleset(self, ruleset_id: int, errors: list[str]) -> RulesetEvidence | None:
        try:
            result = self._transport.request(
                "GET", f"/repos/{self._repository}/rulesets/{ruleset_id}"
            )
        except TransportError as exc:
            errors.append(f"ruleset: {exc}")
            return None
        body = result.body
        if (
            result.status != _HTTP_OK
            or not isinstance(body, dict)
            or not isinstance(body.get("rules"), list)
        ):
            errors.append(f"ruleset: HTTP {result.status} or malformed body")
            return None
        try:
            parsed = parse_rules(body["rules"])
        except RulesParseError as exc:
            errors.append(f"ruleset: {exc}")
            return None
        contexts, strict, tools, unknown = parsed
        ruleset_id_observed = body.get("id")
        return RulesetEvidence(
            ruleset_id=ruleset_id_observed if isinstance(ruleset_id_observed, int) else None,
            enforcement=(body["enforcement"] if isinstance(body.get("enforcement"), str) else None),
            required_status_check_contexts=contexts,
            strict_status_checks=strict,
            code_scanning_tools=tools,
            unknown_rule_types=unknown,
        )

    def _pull_request(self, pr_number: int, errors: list[str]) -> _PullRequestRead | None:
        try:
            result = self._transport.request(
                "POST",
                "/graphql",
                json_body={
                    "query": _PULL_REQUEST_QUERY,
                    "variables": {
                        "owner": self._owner,
                        "name": self._name,
                        "number": pr_number,
                    },
                },
            )
        except TransportError as exc:
            errors.append(f"pull_request: {exc}")
            return None
        body = result.body
        data = body.get("data", {}) if isinstance(body, dict) else {}
        repository = data.get("repository", {}) if isinstance(data, dict) else {}
        pull_request = repository.get("pullRequest") if isinstance(repository, dict) else None
        if result.status != _HTTP_OK or not isinstance(pull_request, dict):
            errors.append(f"pull_request: HTTP {result.status} or missing pull request")
            return None
        threads = pull_request.get("reviewThreads")
        unresolved = _count_unresolved_threads(threads, errors)
        head_sha = pull_request.get("headRefOid")
        base_sha = pull_request.get("baseRefOid")
        merge = pull_request.get("potentialMergeCommit")
        return _PullRequestRead(
            identity=PullRequestIdentity(
                head_sha=head_sha if isinstance(head_sha, str) else "",
                base_sha=base_sha if isinstance(base_sha, str) else "",
                potential_merge_commit_sha=(merge.get("oid") if isinstance(merge, dict) else None),
            ),
            merge_state_status=(
                pull_request["mergeStateStatus"]
                if isinstance(pull_request.get("mergeStateStatus"), str)
                else None
            ),
            unresolved_review_threads=unresolved,
            changes_requested=pull_request.get("reviewDecision") == "CHANGES_REQUESTED",
        )

    def _check_runs(
        self, head_sha: str | None, errors: list[str]
    ) -> tuple[CheckRunEvidence, ...] | None:
        if head_sha is None:
            errors.append("check_runs: skipped, pull request head unavailable")
            return None
        items = self._paginate(
            f"/repos/{self._repository}/commits/{head_sha}/check-runs",
            {"per_page": "100"},
            "check_runs",
            errors,
            "check_runs",
        )
        if items is None:
            return None
        try:
            return tuple(parse_check_run(item) for item in items)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"check_runs: malformed item: {exc}")
            return None

    def _analyses(
        self, pr_number: int, errors: list[str]
    ) -> tuple[CodeScanningAnalysisEvidence, ...] | None:
        items = self._paginate(
            f"/repos/{self._repository}/code-scanning/analyses",
            {"per_page": "100", "ref": f"refs/pull/{pr_number}/merge"},
            None,
            errors,
            "analyses",
        )
        if items is None:
            return None
        analyses: list[CodeScanningAnalysisEvidence] = []
        for item in items:
            raw_tool = item.get("tool")
            tool_name = raw_tool.get("name") if isinstance(raw_tool, dict) else raw_tool
            raw_error = item.get("error")
            analyses.append(
                CodeScanningAnalysisEvidence(
                    tool=str(tool_name) if tool_name is not None else "",
                    commit_sha=str(item.get("commit_sha")),
                    error=str(raw_error) if raw_error else None,
                    created_at=str(item.get("created_at")),
                )
            )
        return tuple(analyses)

    def _alerts(
        self, pr_number: int, contract: DeliveryContract, errors: list[str]
    ) -> tuple[CodeScanningAlertEvidence, ...] | None:
        alerts: dict[int, CodeScanningAlertEvidence] = {}
        for req in contract.required_code_scanning:
            items = self._paginate(
                f"/repos/{self._repository}/code-scanning/alerts",
                {
                    "per_page": "100",
                    "state": "open",
                    "tool_name": req.tool,
                    "ref": f"refs/pull/{pr_number}/merge",
                },
                None,
                errors,
                "alerts",
            )
            if items is None:
                return None
            for item in items:
                rule = item.get("rule")
                rule = rule if isinstance(rule, dict) else {}
                number = item.get("number")
                if not isinstance(number, int):
                    errors.append("alerts: malformed item")
                    return None
                alerts[number] = CodeScanningAlertEvidence(
                    number=number,
                    state=str(item.get("state")),
                    tool=req.tool,
                    security_severity_level=(
                        rule["security_severity_level"]
                        if isinstance(rule.get("security_severity_level"), str)
                        else None
                    ),
                    severity=rule["severity"] if isinstance(rule.get("severity"), str) else None,
                )
        return tuple(alerts.values())


def _load_contract(path: str) -> DeliveryContract:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != _CONTRACT_SCHEMA_VERSION:
        raise ValueError("agent-delivery.json must declare schema_version 3")
    delivery = document["agent_delivery"]
    tools = tuple(
        CodeScanningRequirement(
            tool=str(t["tool"]),
            security_alerts_threshold=str(t["security_alerts_threshold"]),
            alerts_threshold=str(t["alerts_threshold"]),
        )
        for t in delivery["required_code_scanning"]
    )
    return DeliveryContract(
        ruleset_id=int(delivery["ruleset_id"]),
        require_branch_up_to_date=bool(delivery["require_branch_up_to_date"]),
        require_review_thread_resolution=bool(delivery["require_review_thread_resolution"]),
        allow_changes_requested=bool(delivery["allow_changes_requested"]),
        required_status_checks=tuple(str(c) for c in delivery["required_status_checks"]),
        required_code_scanning=tools,
    )


def _report_payload(report: ReadinessReport) -> dict[str, object]:
    return {
        "ready": report.ready,
        "repository": report.repository,
        "ruleset_id": report.ruleset_id,
        "expected_head_sha": report.expected_head_sha,
        "observed_head_sha": report.observed_head_sha,
        "base_sha": report.base_sha,
        "potential_merge_commit_sha": report.potential_merge_commit_sha,
        "blockers": [{"code": b.code.value, "detail": b.detail} for b in report.blockers],
        "evidence_errors": list(report.evidence_errors),
    }


def main(argv: Sequence[str] | None = None, *, transport: GitHubTransport | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blackbread.governance.github_merge_evidence",
        description="Read-only merge-readiness evidence evaluation for one pull request.",
    )
    parser.add_argument("--repository", required=True, help="owner/name")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--expected-head", required=True, help="40-hex pull request head SHA")
    parser.add_argument("--contract", default=".github/agent-delivery.json")
    args = parser.parse_args(argv)
    try:
        contract = _load_contract(args.contract)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        sys.stderr.write(f"contract error: {exc}\n")
        return 2
    if transport is None:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            sys.stderr.write("GITHUB_TOKEN or GH_TOKEN is required\n")
            return 2
        transport = UrllibGitHubTransport(token)
    snapshot = MergeEvidenceCollector(transport, args.repository).collect(args.pr, contract)
    report = evaluate_readiness(contract, snapshot, args.expected_head)
    sys.stdout.write(json.dumps(_report_payload(report), indent=2, sort_keys=True) + "\n")
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
