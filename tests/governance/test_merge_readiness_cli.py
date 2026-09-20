import io
import json
import os
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import blackbread.governance.merge_readiness_cli as cli
from blackbread.governance.merge_readiness import (
    MergeBlocker,
    MergeReadinessDecision,
)


def _base_contract() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "agent_delivery": {
            "owner_instruction_required": True,
            "feature_branch_commit_push_allowed": True,
            "pull_request_required": True,
            "direct_push_main_allowed": False,
            "force_push_allowed": False,
            "expected_head_sha_required": True,
            "required_approving_reviews": 0,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "require_extra_approval_for_unattributed_changes": False,
            "dismiss_stale_reviews": True,
            "require_review_thread_resolution": True,
            "allow_changes_requested": False,
            "require_ai_bot_comment_disposition": False,
            "require_branch_up_to_date": True,
            "required_status_checks": [],
            "required_code_scanning": [],
            "allow_blocking_debt": False,
            "ruleset_id": 123,
        },
    }


_DEFAULT_ARGS = [
    "--repository",
    "owner/repo",
    "--pull-request",
    "123",
    "--expected-head-sha",
    "1234567890abcdef1234567890abcdef12345678",
]


@pytest.fixture
def contract_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    contract_file = tmp_path / ".github" / "agent-delivery.json"
    contract_file.parent.mkdir()
    contract_file.write_text(json.dumps(_base_contract()))
    monkeypatch.setattr(cli, "_get_repo_root", lambda: tmp_path)
    return tmp_path


def _run_with_mocks(monkeypatch: pytest.MonkeyPatch, cwd: Path) -> int:
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
    ) as mock_collect:
        mock_collect.return_value = mock.MagicMock(incomplete_sections=())
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "token"}):
            monkeypatch.chdir(cwd)
            with pytest.raises(SystemExit) as exc:
                cli.main(_DEFAULT_ARGS)
            return exc.value.code


# The test suite for the CLI


def run_cli(
    env: dict[str, str], args: list[str], cwd: str | None = None
) -> subprocess.CompletedProcess[str]:
    with mock.patch.dict(os.environ, env):
        f = io.StringIO()
        with redirect_stdout(f):
            try:
                # Test sets cwd via monkeypatch, but run_cli takes cwd, so let's chdir
                original_cwd = os.getcwd()
                if cwd:
                    os.chdir(cwd)
                try:
                    cli.main(args)
                    code = 0
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else 1
                finally:
                    if cwd:
                        os.chdir(original_cwd)
            except Exception:
                code = 1

        return subprocess.CompletedProcess(
            args=args, returncode=code, stdout=f.getvalue(), stderr=""
        )


def test_invalid_contracts_fail_with_exit_two_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    args = _DEFAULT_ARGS

    monkeypatch.setattr(cli, "_get_repo_root", lambda: tmp_path)

    # Missing .github/agent-delivery.json
    result = run_cli(env, args, cwd=str(tmp_path))
    assert result.returncode == 2

    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    contract_file = github_dir / "agent-delivery.json"

    invalid_json_cases = [
        "not_json",
        '{"schema_version": 3, "agent_delivery": '
        '{"owner_instruction_required": true, "owner_instruction_required": false}}',
        '{"schema_version": 3, "unknown_key": 1}',
        '{"schema_version": 3}',
        '{"schema_version": 999, "agent_delivery": {}}',
        '{"schema_version": 3, "agent_delivery": '
        '{"required_status_checks": [{"context": "ci-ok", "integration_id": "not_an_int"}]}}',
    ]

    for case in invalid_json_cases:
        contract_file.write_text(case)
        res = run_cli(env, args, cwd=str(tmp_path))
        assert res.returncode == 2
        out = json.loads(res.stdout.strip())
        assert out["status"] == "error"
        assert out["ready"] is False
        assert out["schema_version"] == 1
        assert "errors" in out


def test_dynamic_boolean_validation_rejects_non_booleans_with_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    args = _DEFAULT_ARGS

    monkeypatch.setattr(cli, "_get_repo_root", lambda: tmp_path)

    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    contract_file = github_dir / "agent-delivery.json"

    base_contract = _base_contract()

    invalid_values = ["false", 0, 1, None, [], "true"]
    boolean_fields = ["require_review_thread_resolution", "allow_changes_requested"]

    for field in boolean_fields:
        for val in invalid_values:
            mod = json.loads(json.dumps(base_contract))
            mod["agent_delivery"][field] = val
            contract_file.write_text(json.dumps(mod))
            res = run_cli(env, args, cwd=str(tmp_path))
            assert res.returncode == 2, f"Failed to reject {field}={val!r}"
            out = json.loads(res.stdout.strip())
            assert out["status"] == "error"
            assert out["ready"] is False
            assert "CONTRACT_INVALID_TYPE" in out["errors"]


def test_invalid_code_scanning_thresholds_return_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    args = _DEFAULT_ARGS

    monkeypatch.setattr(cli, "_get_repo_root", lambda: tmp_path)

    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    contract_file = github_dir / "agent-delivery.json"

    base_contract = _base_contract()

    invalid_cases = [
        {"tool": "CodeQL", "security_alerts_threshold": "errors", "alerts_threshold": "errors"},
        {
            "tool": "CodeQL",
            "security_alerts_threshold": "high_or_higher",
            "alerts_threshold": "high_or_higher",
        },
        {"tool": "CodeQL", "security_alerts_threshold": "unknown", "alerts_threshold": "errors"},
        {
            "tool": "CodeQL",
            "security_alerts_threshold": "high_or_higher",
            "alerts_threshold": "unknown",
        },
    ]

    for req in invalid_cases:
        contract = json.loads(json.dumps(base_contract))
        contract["agent_delivery"]["required_code_scanning"] = [req]
        contract_file.write_text(json.dumps(contract))
        res = run_cli(env, args, cwd=str(tmp_path))
        assert res.returncode == 2
        out = json.loads(res.stdout.strip())
        assert out["status"] == "error"
        assert "CONTRACT_INVALID_CODE_SCANNING" in out["errors"]


def test_expected_head_is_passed_unchanged_and_mismatch_returns_two(
    contract_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # We will mock the evaluate_merge_readiness function via patching
    # But since it's a subprocess, we can't easily mock it unless we write a small script
    # Let's import the cli directly in the test to test internal composition
    # We can use mock.patch to track the arguments
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
    ) as mock_eval:
        mock_eval.return_value = MergeReadinessDecision(
            ready=False, blockers=(MergeBlocker("HEAD_SHA_MISMATCH", "expected != actual"),)
        )

        code = _run_with_mocks(monkeypatch, contract_env)
        assert code == 2
        mock_eval.assert_called_once()
        args = mock_eval.call_args[0]
        assert args[2] == "1234567890abcdef1234567890abcdef12345678"


def test_complete_ready_evidence_returns_zero_with_canonical_output(
    contract_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
    ) as mock_eval:
        mock_eval.return_value = MergeReadinessDecision(ready=True, blockers=())
        with (
            mock.patch(
                "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
            ) as mock_collect,
            mock.patch("sys.stdout.write") as mock_stdout,
        ):
            mock_collect.return_value = mock.MagicMock(incomplete_sections=())
            with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "token"}):
                monkeypatch.chdir(contract_env)
                with pytest.raises(SystemExit) as exc:
                    cli.main(
                        [
                            "--repository",
                            "owner/repo",
                            "--pull-request",
                            "123",
                            "--expected-head-sha",
                            "1234567890abcdef1234567890abcdef12345678",
                        ]
                    )
            assert exc.value.code == 0
            out_str = "".join(call[0][0] for call in mock_stdout.call_args_list)
            out = json.loads(out_str)
            assert out["ready"] is True
            assert out["status"] == "ready"
            assert out["blockers"] == []


def test_complete_substantive_blockers_return_one(
    contract_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
    ) as mock_eval:
        mock_eval.return_value = MergeReadinessDecision(
            ready=False, blockers=(MergeBlocker("CHANGES_REQUESTED", "detail"),)
        )
        code = _run_with_mocks(monkeypatch, contract_env)
        assert code == 1

        mock_eval.return_value = MergeReadinessDecision(
            ready=False, blockers=(MergeBlocker("UNKNOWN_BLOCKER", "detail"),)
        )
        code = _run_with_mocks(monkeypatch, contract_env)
        assert code == 2


def test_incomplete_or_drifted_evidence_returns_two(
    contract_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
    ) as mock_eval:
        mock_eval.return_value = MergeReadinessDecision(
            ready=False, blockers=(MergeBlocker("INCOMPLETE_EVIDENCE", "pagination"),)
        )
        code = _run_with_mocks(monkeypatch, contract_env)
        assert code == 2


def test_token_remote_text_and_exception_text_never_reach_output(
    contract_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
    ) as mock_collect:
        mock_collect.side_effect = Exception("hostile_remote_text_my_secret_token_123")
        with mock.patch("sys.stdout.write") as mock_stdout:
            with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "my_secret_token_123"}):
                monkeypatch.chdir(contract_env)
                with pytest.raises(SystemExit) as exc:
                    cli.main(
                        [
                            "--repository",
                            "owner/repo",
                            "--pull-request",
                            "123",
                            "--expected-head-sha",
                            "1234567890abcdef1234567890abcdef12345678",
                        ]
                    )
            assert exc.value.code == 2
            out_str = "".join(call[0][0] for call in mock_stdout.call_args_list)
            assert "hostile_remote" not in out_str
            assert "my_secret_token_123" not in out_str
            out = json.loads(out_str)
            assert out["status"] == "error"


def test_cli_constructs_urllib_transport_collector_and_existing_evaluator(
    contract_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        mock.patch(
            "blackbread.governance.merge_readiness_cli.UrllibGitHubReadTransport"
        ) as mock_transport,
        mock.patch(
            "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector"
        ) as mock_collector_cls,
    ):
        mock_collector = mock.MagicMock()
        mock_collector.collect.return_value = mock.MagicMock(incomplete_sections=())
        mock_collector_cls.return_value = mock_collector
        with mock.patch(
            "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
        ) as mock_eval:
            mock_eval.return_value = MergeReadinessDecision(ready=True, blockers=())
            with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "token"}):
                monkeypatch.chdir(contract_env)
                with pytest.raises(SystemExit) as exc:
                    cli.main(
                        [
                            "--repository",
                            "owner/repo",
                            "--pull-request",
                            "123",
                            "--expected-head-sha",
                            "1234567890abcdef1234567890abcdef12345678",
                        ]
                    )
            assert exc.value.code == 0
            mock_transport.assert_called_once_with("token")
            mock_collector_cls.assert_called_once_with(mock_transport.return_value, "owner/repo")
            mock_collector.collect.assert_called_once()
            mock_eval.assert_called_once()


def test_smoke_document_names_exact_command_exit_contract_and_redaction() -> None:
    doc_path = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "qualification"
        / "github-merge-readiness-smoke.md"
    )
    assert doc_path.exists(), f"Smoke doc not found at {doc_path}"
    content = doc_path.read_text(encoding="utf-8")
    assert "uv run python -m blackbread.governance.merge_readiness_cli" in content
    assert "--repository" in content
    assert "--pull-request" in content
    assert "--expected-head-sha" in content
    assert "GITHUB_TOKEN" in content
    assert "Exit 2" in content
    assert "never log or print" in content.lower()


def test_help_invocation_returns_exit_two_with_canonical_json(tmp_path: Path) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    res = run_cli(env, ["--help"], cwd=str(tmp_path))
    assert res.returncode == 2
    assert "usage:" not in res.stdout.lower()
    assert "help" not in res.stdout.lower()
    out = json.loads(res.stdout.strip())
    assert out["status"] == "error"
    assert out["ready"] is False
    assert out["schema_version"] == 1
    assert "errors" in out


def test_contract_loaded_from_repo_root_ignores_cwd_decoy(tmp_path: Path) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    decoy_dir = tmp_path / ".github"
    decoy_dir.mkdir()
    decoy_contract = decoy_dir / "agent-delivery.json"

    # Decoy allows changes requested and disables threads
    base = _base_contract()
    base["agent_delivery"]["require_review_thread_resolution"] = False
    base["agent_delivery"]["allow_changes_requested"] = True
    base["agent_delivery"]["ruleset_id"] = 21644438
    decoy_contract.write_text(json.dumps(base))

    with mock.patch(
        "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
    ) as mock_eval:
        mock_eval.return_value = MergeReadinessDecision(ready=True, blockers=())
        with mock.patch(
            "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
        ) as mock_collect:
            mock_collect.return_value = mock.MagicMock(incomplete_sections=())
            res = run_cli(
                env,
                _DEFAULT_ARGS,
                cwd=str(tmp_path),
            )
            assert res.returncode == 0

            contract = mock_eval.call_args[0][0]
            assert contract.require_review_thread_resolution is True
            assert contract.allow_changes_requested is False


def test_unsupported_static_policy_flags_return_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    args = _DEFAULT_ARGS
    monkeypatch.setattr(cli, "_get_repo_root", lambda: tmp_path)
    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    contract_file = github_dir / "agent-delivery.json"

    base_contract = _base_contract()

    contract_file.write_text(json.dumps(base_contract))
    # Let's mock collect to ensure we only test loading.
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
    ) as mock_eval:
        mock_eval.return_value = MergeReadinessDecision(ready=True, blockers=())
        with mock.patch(
            "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
        ) as mock_collect:
            mock_collect.return_value = mock.MagicMock(incomplete_sections=())
            res = run_cli(env, args, cwd=str(tmp_path))
            assert res.returncode == 0

            # Test specifically flipping require_ai_bot_comment_disposition
            mod_contract = json.loads(json.dumps(base_contract))
            mod_contract["agent_delivery"]["require_ai_bot_comment_disposition"] = True
            contract_file.write_text(json.dumps(mod_contract))
            res = run_cli(env, args, cwd=str(tmp_path))
            assert res.returncode == 2
            out = json.loads(res.stdout.strip())
            assert "CONTRACT_UNSUPPORTED_POLICY" in out["errors"]

            # Test flipping all unsupported fields
            unsupported = [
                "owner_instruction_required",
                "feature_branch_commit_push_allowed",
                "pull_request_required",
                "direct_push_main_allowed",
                "force_push_allowed",
                "expected_head_sha_required",
                "require_code_owner_review",
                "require_last_push_approval",
                "require_extra_approval_for_unattributed_changes",
                "dismiss_stale_reviews",
                "require_ai_bot_comment_disposition",
                "require_branch_up_to_date",
                "allow_blocking_debt",
            ]
            for key in unsupported:
                mod = json.loads(json.dumps(base_contract))
                mod["agent_delivery"][key] = not base_contract["agent_delivery"][key]
                contract_file.write_text(json.dumps(mod))
                res = run_cli(env, args, cwd=str(tmp_path))
                assert res.returncode == 2
                out = json.loads(res.stdout.strip())
                assert "CONTRACT_UNSUPPORTED_POLICY" in out["errors"]
