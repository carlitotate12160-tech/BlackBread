import io
import json
import os
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

import blackbread.governance.merge_readiness_cli as cli
from blackbread.governance.merge_readiness import (
    MergeBlocker,
    MergeReadinessDecision,
)


@pytest.fixture
def contract_env(tmp_path: Path) -> Path:
    contract_file = tmp_path / ".github" / "agent-delivery.json"
    contract_file.parent.mkdir()
    contract_file.write_text(
        json.dumps(
            {
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
        )
    )
    return tmp_path


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


def test_invalid_contracts_fail_with_exit_two_before_io(tmp_path: Path) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    args = [
        "--repository",
        "owner/repo",
        "--pull-request",
        "123",
        "--expected-head-sha",
        "1234567890abcdef1234567890abcdef12345678",
    ]

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


def test_invalid_code_scanning_thresholds_return_exit_two(tmp_path: Path) -> None:
    env = {"GITHUB_TOKEN": "valid_token"}
    args = [
        "--repository",
        "owner/repo",
        "--pull-request",
        "123",
        "--expected-head-sha",
        "1234567890abcdef1234567890abcdef12345678",
    ]

    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    contract_file = github_dir / "agent-delivery.json"

    base_contract = {
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

    invalid_cases = [
        # 'errors' rejected as security_alerts_threshold
        {"tool": "CodeQL", "security_alerts_threshold": "errors", "alerts_threshold": "errors"},
        # 'high_or_higher' rejected as alerts_threshold
        {
            "tool": "CodeQL",
            "security_alerts_threshold": "high_or_higher",
            "alerts_threshold": "high_or_higher",
        },
        # Unknown thresholds
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

        with mock.patch(
            "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
        ) as mock_collect:
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

            assert exc.value.code == 2
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
        with mock.patch(
            "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
        ) as mock_collect:
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
            assert exc.value.code == 1

        mock_eval.return_value = MergeReadinessDecision(
            ready=False, blockers=(MergeBlocker("UNKNOWN_BLOCKER", "detail"),)
        )
        with mock.patch(
            "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
        ) as mock_collect:
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
            assert exc.value.code == 2


def test_incomplete_or_drifted_evidence_returns_two(
    contract_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with mock.patch(
        "blackbread.governance.merge_readiness_cli.evaluate_merge_readiness"
    ) as mock_eval:
        mock_eval.return_value = MergeReadinessDecision(
            ready=False, blockers=(MergeBlocker("INCOMPLETE_EVIDENCE", "pagination"),)
        )
        with mock.patch(
            "blackbread.governance.merge_readiness_cli.GitHubMergeEvidenceCollector.collect"
        ) as mock_collect:
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
            assert exc.value.code == 2


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
    assert "Exit 0" in content
    assert "Exit 1" in content
    assert "Exit 2" in content
    assert "never log or print" in content.lower()
