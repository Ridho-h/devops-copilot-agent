import json
import pytest
from unittest.mock import MagicMock, patch
from agent.orchestrator import DevOpsOrchestrator, RunFinding, RunSummary


@pytest.fixture
def mock_clean_repo_state():
    return {
        "repo": "test-owner/test-repo",
        "default_branch": "main",
        "description": "Clean test repository",
        "recent_commits": [{"sha": "sha1", "commit": {"message": "feat: clean"}}],
        "open_issues": [],
        "open_prs": [],
        "ci_status": {
            "status": "passing",
            "latest_run": 100,
            "latest_conclusion": "success",
            "latest_status": "completed",
            "failing_runs": [],
            "total_runs": 1,
        },
        "dependencies": {},
    }


@pytest.fixture
def mock_failing_ci_repo_state():
    return {
        "repo": "test-owner/test-repo",
        "default_branch": "main",
        "description": "Repo with failing CI",
        "recent_commits": [{"sha": "sha1", "commit": {"message": "feat: broken"}}],
        "open_issues": [],
        "open_prs": [],
        "ci_status": {
            "status": "failing",
            "latest_run": 105,
            "latest_conclusion": "failure",
            "latest_status": "completed",
            "failing_runs": [
                {
                    "id": 105,
                    "name": "Build & Test",
                    "head_branch": "main",
                    "conclusion": "failure",
                    "html_url": "https://github.com/test-owner/test-repo/actions/runs/105",
                    "created_at": "2026-09-26T10:00:00Z",
                }
            ],
            "total_runs": 2,
        },
        "dependencies": {},
    }


def test_orchestrator_initialization():
    orchestrator = DevOpsOrchestrator(repo="owner/repo", token="dummy-token", api_key="dummy-key")
    assert orchestrator.repo == "owner/repo"
    assert orchestrator.token == "dummy-token"


@patch("agent.orchestrator.check_outdated_dependencies")
@patch("agent.orchestrator.get_stale_branches")
@patch("agent.orchestrator.get_repo_state")
@patch("agent.orchestrator.open_issue")
def test_decision_loop_clean_repo_does_nothing(
    mock_open_issue, mock_get_repo_state, mock_get_stale, mock_check_deps, mock_clean_repo_state, tmp_path
):
    mock_get_repo_state.return_value = mock_clean_repo_state
    mock_get_stale.return_value = []
    mock_check_deps.return_value = []

    log_file = tmp_path / "run_log.json"
    orchestrator = DevOpsOrchestrator(repo="test-owner/test-repo", log_path=str(log_file))

    summary = orchestrator.run()

    # Rule: A quiet run is a correct outcome, not a failure.
    assert summary.repo == "test-owner/test-repo"
    assert len(summary.findings) == 0
    assert "no action needed" in summary.summary.lower()
    mock_open_issue.assert_not_called()

    # Verify log file was written
    assert log_file.exists()
    saved_log = json.loads(log_file.read_text())
    assert saved_log["repo"] == "test-owner/test-repo"
    assert len(saved_log["findings"]) == 0


@patch("agent.orchestrator.get_stale_branches")
@patch("agent.orchestrator.get_repo_state")
@patch("agent.orchestrator.open_issue")
def test_decision_loop_ci_failure_opens_issue(mock_open_issue, mock_get_repo_state, mock_get_stale, mock_failing_ci_repo_state, tmp_path):
    mock_get_repo_state.return_value = mock_failing_ci_repo_state
    mock_get_stale.return_value = []
    mock_open_issue.return_value = {
        "number": 55,
        "html_url": "https://github.com/test-owner/test-repo/issues/55",
        "title": "CI failing on main",
    }

    log_file = tmp_path / "run_log.json"
    orchestrator = DevOpsOrchestrator(repo="test-owner/test-repo", log_path=str(log_file))

    summary = orchestrator.run()

    # Check that CI failure took priority and triggered open_issue
    assert len(summary.findings) == 1
    finding = summary.findings[0]
    assert finding.type == "ci_failure"
    assert finding.action_taken == "issue"
    assert finding.reference == "https://github.com/test-owner/test-repo/issues/55"
    mock_open_issue.assert_called_once()
    assert "CI failing on main" in mock_open_issue.call_args[1]["title"]


@patch("agent.orchestrator.get_stale_branches")
@patch("agent.orchestrator.get_repo_state")
@patch("agent.orchestrator.open_issue")
def test_decision_loop_prevents_duplicate_issue(mock_open_issue, mock_get_repo_state, mock_get_stale, mock_failing_ci_repo_state, tmp_path):
    # Already have an open issue about CI failing
    mock_failing_ci_repo_state["open_issues"] = [
        {"number": 50, "title": "CI failing on main", "html_url": "https://github.com/test-owner/test-repo/issues/50"}
    ]
    mock_get_repo_state.return_value = mock_failing_ci_repo_state
    mock_get_stale.return_value = []

    log_file = tmp_path / "run_log.json"
    orchestrator = DevOpsOrchestrator(repo="test-owner/test-repo", log_path=str(log_file))

    summary = orchestrator.run()

    # Should recognize existing issue and NOT open a duplicate issue
    mock_open_issue.assert_not_called()
    assert len(summary.findings) == 1
    assert summary.findings[0].action_taken == "none"
    assert "already open" in summary.findings[0].evidence.lower() or "duplicate" in summary.findings[0].evidence.lower()


@patch("agent.orchestrator.check_outdated_dependencies")
@patch("agent.orchestrator.get_stale_branches")
@patch("agent.orchestrator.get_repo_state")
@patch("agent.orchestrator.open_issue")
def test_decision_loop_stale_branches_opens_issue(
    mock_open_issue, mock_get_repo_state, mock_get_stale, mock_check_deps, mock_clean_repo_state, tmp_path
):
    mock_get_repo_state.return_value = mock_clean_repo_state
    mock_get_stale.return_value = [
        {"name": "old-feature", "sha": "12345", "days_inactive": 45, "last_commit_date": "2026-08-01T00:00:00Z"}
    ]
    mock_check_deps.return_value = []
    mock_open_issue.return_value = {
        "number": 56,
        "html_url": "https://github.com/test-owner/test-repo/issues/56",
        "title": "Stale branches detected",
    }

    log_file = tmp_path / "run_log.json"
    orchestrator = DevOpsOrchestrator(repo="test-owner/test-repo", log_path=str(log_file))

    summary = orchestrator.run()

    assert len(summary.findings) == 1
    finding = summary.findings[0]
    assert finding.type == "stale_branches"
    assert finding.action_taken == "issue"
    mock_open_issue.assert_called_once()
    assert "stale" in mock_open_issue.call_args[1]["title"].lower()


@patch("agent.orchestrator.get_stale_branches")
@patch("agent.orchestrator.get_repo_state")
@patch("agent.orchestrator.open_issue")
def test_decision_loop_dry_run_mode(mock_open_issue, mock_get_repo_state, mock_get_stale, mock_failing_ci_repo_state, tmp_path):
    mock_get_repo_state.return_value = mock_failing_ci_repo_state
    mock_get_stale.return_value = []

    log_file = tmp_path / "run_log.json"
    orchestrator = DevOpsOrchestrator(repo="test-owner/test-repo", log_path=str(log_file), dry_run=True)

    summary = orchestrator.run()

    # In dry run mode, open_issue should NOT be called over the network
    mock_open_issue.assert_not_called()
    assert len(summary.findings) == 1
    assert "dry_run" in summary.findings[0].action_taken


@patch("agent.orchestrator.check_outdated_dependencies")
@patch("agent.orchestrator.get_stale_branches")
@patch("agent.orchestrator.get_repo_state")
@patch("agent.orchestrator.open_issue")
def test_decision_loop_outdated_dependencies_opens_issue(
    mock_open_issue, mock_get_repo_state, mock_get_stale, mock_check_deps, mock_clean_repo_state, tmp_path
):
    mock_get_repo_state.return_value = mock_clean_repo_state
    mock_get_stale.return_value = []
    mock_check_deps.return_value = [
        {"package": "requests", "current_version": "2.25.0", "latest_version": "2.31.0", "is_outdated": True}
    ]
    mock_open_issue.return_value = {
        "number": 57,
        "html_url": "https://github.com/test-owner/test-repo/issues/57",
        "title": "Outdated dependencies detected (1 package(s))",
    }

    log_file = tmp_path / "run_log.json"
    orchestrator = DevOpsOrchestrator(repo="test-owner/test-repo", log_path=str(log_file))

    summary = orchestrator.run()

    assert len(summary.findings) == 1
    finding = summary.findings[0]
    assert finding.type == "outdated_dependencies"
    assert finding.action_taken == "issue"
    assert "requests" in finding.evidence
    mock_open_issue.assert_called_once()
    assert "outdated dependencies" in mock_open_issue.call_args[1]["title"].lower()


@patch("agent.orchestrator.check_outdated_dependencies")
@patch("agent.orchestrator.get_stale_branches")
@patch("agent.orchestrator.get_repo_state")
@patch("agent.orchestrator.open_issue")
def test_decision_loop_outdated_dependencies_duplicate_suppression(
    mock_open_issue, mock_get_repo_state, mock_get_stale, mock_check_deps, mock_clean_repo_state, tmp_path
):
    mock_clean_repo_state["open_issues"] = [
        {"number": 52, "title": "Outdated dependencies detected (1 package(s))", "html_url": "https://github.com/test-owner/test-repo/issues/52"}
    ]
    mock_get_repo_state.return_value = mock_clean_repo_state
    mock_get_stale.return_value = []
    mock_check_deps.return_value = [
        {"package": "requests", "current_version": "2.25.0", "latest_version": "2.31.0", "is_outdated": True}
    ]

    log_file = tmp_path / "run_log.json"
    orchestrator = DevOpsOrchestrator(repo="test-owner/test-repo", log_path=str(log_file))

    summary = orchestrator.run()

    mock_open_issue.assert_not_called()
    assert len(summary.findings) == 1
    assert summary.findings[0].action_taken == "none"
    assert "already tracked" in summary.findings[0].evidence.lower() or "already open" in summary.findings[0].evidence.lower()
