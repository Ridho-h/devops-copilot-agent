import pytest
from unittest.mock import patch, MagicMock
from agent.tools.github_tools import (
    GitHubClient,
    get_repo_info,
    get_commits,
    get_issues,
    get_pull_requests,
    get_ci_status,
    list_dependencies,
    get_stale_branches,
    get_repo_state,
    open_issue,
    open_pr,
    get_rate_limit,
)


def test_github_client_headers():
    client = GitHubClient(token="my-token")
    headers = client._get_headers()
    assert headers["Authorization"] == "Bearer my-token"
    assert headers["Accept"] == "application/vnd.github.v3+json"


def test_github_client_headers_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = GitHubClient(token=None)
    headers = client._get_headers()
    assert "Authorization" not in headers


@patch("agent.tools.github_tools.requests.request")
def test_get_repo_info(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "full_name": "owner/repo",
        "default_branch": "main",
        "description": "Test repo",
        "open_issues_count": 5,
    }
    mock_request.return_value = mock_resp

    info = get_repo_info("owner/repo", token="test-token")
    assert info["full_name"] == "owner/repo"
    assert info["default_branch"] == "main"
    assert mock_request.call_args[0][0] == "GET"


@patch("agent.tools.github_tools.requests.request")
def test_get_commits(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"sha": "c123456", "commit": {"message": "feat: initial commit", "author": {"date": "2026-09-01T00:00:00Z"}}}
    ]
    mock_request.return_value = mock_resp

    commits = get_commits("owner/repo", limit=5, token="test-token")
    assert len(commits) == 1
    assert commits[0]["sha"] == "c123456"


@patch("agent.tools.github_tools.requests.request")
def test_get_issues_filters_out_prs(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"number": 1, "title": "Actual issue", "state": "open"},
        {"number": 2, "title": "Pull request", "state": "open", "pull_request": {"url": "..."}},
    ]
    mock_request.return_value = mock_resp

    issues = get_issues("owner/repo", token="test-token")
    assert len(issues) == 1
    assert issues[0]["title"] == "Actual issue"


@patch("agent.tools.github_tools.requests.request")
def test_get_pull_requests(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"number": 2, "title": "Pull request", "state": "open", "head": {"ref": "feature-1"}}
    ]
    mock_request.return_value = mock_resp

    prs = get_pull_requests("owner/repo", token="test-token")
    assert len(prs) == 1
    assert prs[0]["number"] == 2


@patch("agent.tools.github_tools.requests.request")
def test_get_ci_status_with_workflow_runs(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "total_count": 2,
        "workflow_runs": [
            {
                "id": 101,
                "name": "CI",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/owner/repo/actions/runs/101",
                "created_at": "2026-09-20T10:00:00Z",
            },
            {
                "id": 100,
                "name": "CI",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/owner/repo/actions/runs/100",
                "created_at": "2026-09-19T10:00:00Z",
            },
        ],
    }
    mock_request.return_value = mock_resp

    ci = get_ci_status("owner/repo", branch="main", token="test-token")
    assert ci["status"] == "failing"
    assert ci["latest_conclusion"] == "failure"
    assert len(ci["failing_runs"]) == 1
    assert ci["failing_runs"][0]["id"] == 101


@patch("agent.tools.github_tools.requests.request")
def test_list_dependencies_requirements_txt(mock_request):
    import base64

    content_raw = "requests==2.31.0\npydantic>=2.0.0\n# comment\npytest\n"
    encoded = base64.b64encode(content_raw.encode()).decode()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "requirements.txt",
        "encoding": "base64",
        "content": encoded,
    }
    mock_request.return_value = mock_resp

    deps = list_dependencies("owner/repo", path="requirements.txt", token="test-token")
    assert deps["requests"] == "==2.31.0"
    assert deps["pydantic"] == ">=2.0.0"
    assert deps["pytest"] == "*"


@patch("agent.tools.github_tools.requests.request")
def test_list_dependencies_package_json(mock_request):
    import base64

    content_raw = '{"dependencies": {"express": "^4.18.2"}, "devDependencies": {"jest": "^29.0.0"}}'
    encoded = base64.b64encode(content_raw.encode()).decode()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "package.json",
        "encoding": "base64",
        "content": encoded,
    }
    mock_request.return_value = mock_resp

    deps = list_dependencies("owner/repo", path="package.json", token="test-token")
    assert deps["express"] == "^4.18.2"
    assert deps["jest"] == "^29.0.0"


@patch("agent.tools.github_tools.requests.request")
def test_get_stale_branches(mock_request):
    branches_resp = MagicMock()
    branches_resp.status_code = 200
    branches_resp.json.return_value = [
        {"name": "main"},
        {"name": "feature/old-stuff", "commit": {"sha": "sha_old"}},
    ]

    commit_resp = MagicMock()
    commit_resp.status_code = 200
    commit_resp.json.return_value = {
        "commit": {
            "committer": {"date": "2026-01-01T00:00:00Z"}
        }
    }

    mock_request.side_effect = [branches_resp, commit_resp]

    stale = get_stale_branches("owner/repo", days_threshold=30, default_branch="main", token="test-token")
    assert len(stale) == 1
    assert stale[0]["name"] == "feature/old-stuff"
    assert stale[0]["days_inactive"] > 30


@patch("agent.tools.github_tools.requests.request")
def test_open_issue(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": 12345,
        "number": 42,
        "title": "CI failing on main",
        "html_url": "https://github.com/owner/repo/issues/42",
        "state": "open",
    }
    mock_request.return_value = mock_resp

    issue = open_issue(
        repo="owner/repo",
        title="CI failing on main",
        body="Details on the failure...",
        labels=["devops-copilot", "ci-failure"],
        token="test-token",
    )
    assert issue["number"] == 42
    assert issue["html_url"] == "https://github.com/owner/repo/issues/42"
    mock_request.assert_called_once()
    assert mock_request.call_args[0][0] == "POST"
    payload = mock_request.call_args[1]["json"]
    assert payload["title"] == "CI failing on main"
    assert payload["labels"] == ["devops-copilot", "ci-failure"]


@patch("agent.tools.github_tools.GitHubClient.get")
@patch("agent.tools.github_tools.GitHubClient.post")
@patch("agent.tools.github_tools.GitHubClient.put")
def test_open_pr(mock_put, mock_post, mock_get):
    # Mock ref heads/main
    mock_get.return_value = {"object": {"sha": "base_sha_123"}}
    # Mock post ref (create branch) and PR
    mock_post.side_effect = [
        {"ref": "refs/heads/fix/ci"},  # create ref
        {  # create PR
            "id": 99,
            "number": 10,
            "title": "Fix CI script",
            "html_url": "https://github.com/owner/repo/pull/10",
            "state": "open",
            "head": {"ref": "fix/ci"},
            "base": {"ref": "main"},
        },
    ]

    pr = open_pr(
        repo="owner/repo",
        title="Fix CI script",
        body="Fixes CI by updating configs",
        branch="fix/ci",
        base="main",
        token="test-token",
    )
    assert pr["number"] == 10
    assert pr["html_url"] == "https://github.com/owner/repo/pull/10"


@patch("agent.tools.github_tools.get_repo_info")
@patch("agent.tools.github_tools.get_commits")
@patch("agent.tools.github_tools.get_issues")
@patch("agent.tools.github_tools.get_pull_requests")
@patch("agent.tools.github_tools.get_ci_status")
@patch("agent.tools.github_tools.list_dependencies")
def test_get_repo_state(mock_deps, mock_ci, mock_prs, mock_issues, mock_commits, mock_info):
    mock_info.return_value = {"full_name": "owner/repo", "default_branch": "main"}
    mock_commits.return_value = [{"sha": "abc", "commit": {"message": "test"}}]
    mock_issues.return_value = [{"number": 1, "title": "issue"}]
    mock_prs.return_value = [{"number": 2, "title": "pr"}]
    mock_ci.return_value = {"status": "passing"}
    mock_deps.return_value = {"pytest": "*"}

    state = get_repo_state("owner/repo", token="test-token")
    assert state["repo"] == "owner/repo"
    assert state["default_branch"] == "main"
    assert len(state["recent_commits"]) == 1
    assert len(state["open_issues"]) == 1
    assert len(state["open_prs"]) == 1
    assert state["ci_status"]["status"] == "passing"
    assert state["dependencies"]["pytest"] == "*"


@patch("agent.tools.github_tools.requests.request")
def test_get_rate_limit(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "resources": {
            "core": {
                "limit": 5000,
                "remaining": 4990,
                "reset": 1700000000,
                "used": 10,
            }
        }
    }
    mock_request.return_value = mock_resp

    rl = get_rate_limit(token="test-token")
    assert rl["core"]["remaining"] == 4990
    assert rl["core"]["limit"] == 5000


@patch("agent.tools.github_tools.requests.request")
def test_list_dependencies_no_manifests(mock_request):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json.return_value = {"message": "Not Found"}
    mock_request.return_value = mock_resp

    deps = list_dependencies("owner/repo", token="test-token")
    assert deps == {}


def test_open_pr_same_branch_raises_value_error():
    with pytest.raises(ValueError, match="cannot be identical"):
        open_pr("owner/repo", "Title", "Body", branch="main", base="main", token="test-token")
