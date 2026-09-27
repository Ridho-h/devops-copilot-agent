"""GitHub automation tools for DevOps Copilot Agent."""

import base64
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests


class GitHubClient:
    """Lightweight REST client for GitHub API."""

    def __init__(self, token: Optional[str] = None, base_url: str = "https://api.github.com"):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.base_url = base_url.rstrip("/")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "DevOps-Copilot-Agent",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        response = requests.request(method, url, headers=headers, **kwargs)
        if response.status_code >= 400:
            try:
                error_body = response.json()
            except Exception:
                error_body = response.text
            raise RuntimeError(
                f"GitHub API error {response.status_code} on {method} {url}: {error_body}"
            )
        if response.status_code == 204:
            return None
        return response.json()

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("POST", endpoint, json=json)

    def put(self, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("PUT", endpoint, json=json)

    def patch(self, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("PATCH", endpoint, json=json)

    def delete(self, endpoint: str) -> Any:
        return self.request("DELETE", endpoint)


def _get_client(token: Optional[str] = None) -> GitHubClient:
    return GitHubClient(token=token)


def get_rate_limit(token: Optional[str] = None) -> Dict[str, Any]:
    """Check remaining GitHub API rate limits."""
    client = _get_client(token)
    data = client.get("/rate_limit")
    return data.get("resources", {})


def get_repo_info(repo: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch repository metadata."""
    client = _get_client(token)
    return client.get(f"/repos/{repo}")


def get_commits(
    repo: str, limit: int = 10, branch: Optional[str] = None, token: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetch recent commit history."""
    client = _get_client(token)
    params = {"per_page": limit}
    if branch:
        params["sha"] = branch
    return client.get(f"/repos/{repo}/commits", params=params)


def get_issues(
    repo: str, state: str = "open", limit: int = 20, token: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetch issues (excluding pull requests)."""
    client = _get_client(token)
    params = {"state": state, "per_page": limit}
    items = client.get(f"/repos/{repo}/issues", params=params)
    return [item for item in items if "pull_request" not in item]


def get_pull_requests(
    repo: str, state: str = "open", limit: int = 20, token: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetch pull requests."""
    client = _get_client(token)
    params = {"state": state, "per_page": limit}
    return client.get(f"/repos/{repo}/pulls", params=params)


def get_ci_status(
    repo: str, branch: Optional[str] = None, token: Optional[str] = None
) -> Dict[str, Any]:
    """Fetch CI workflow run status for a repository and branch."""
    client = _get_client(token)
    params: Dict[str, Any] = {"per_page": 10}
    if branch:
        params["branch"] = branch

    data = client.get(f"/repos/{repo}/actions/runs", params=params)
    runs = data.get("workflow_runs", [])

    if not runs:
        return {
            "status": "unknown",
            "latest_run": None,
            "latest_conclusion": None,
            "failing_runs": [],
            "total_runs": 0,
        }

    latest = runs[0]
    latest_conclusion = latest.get("conclusion")
    latest_status = latest.get("status")

    failing_runs = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "head_branch": r.get("head_branch"),
            "status": r.get("status"),
            "conclusion": r.get("conclusion"),
            "html_url": r.get("html_url"),
            "created_at": r.get("created_at"),
        }
        for r in runs
        if r.get("conclusion") in ("failure", "timed_out", "startup_failure")
    ]

    status = "passing"
    if latest_conclusion in ("failure", "timed_out", "startup_failure"):
        status = "failing"
    elif latest_status in ("queued", "in_progress"):
        status = "in_progress"

    return {
        "status": status,
        "latest_run": latest.get("id"),
        "latest_conclusion": latest_conclusion,
        "latest_status": latest_status,
        "failing_runs": failing_runs,
        "total_runs": len(runs),
    }


def _parse_requirements_txt(content: str) -> Dict[str, str]:
    deps: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = re.split(r"(==|>=|<=|~=|>|<|!=)", line, maxsplit=1)
        if len(match) == 3:
            pkg = match[0].strip()
            spec = match[1] + match[2].strip()
            deps[pkg] = spec
        else:
            deps[line.strip()] = "*"
    return deps


def _parse_package_json(content: str) -> Dict[str, str]:
    deps: Dict[str, str] = {}
    try:
        data = json.loads(content)
        deps.update(data.get("dependencies", {}))
        deps.update(data.get("devDependencies", {}))
    except Exception:
        pass
    return deps


def list_dependencies(
    repo: str, path: Optional[str] = None, token: Optional[str] = None
) -> Dict[str, str]:
    """List dependencies from repository manifest files."""
    client = _get_client(token)

    candidates = [path] if path else ["requirements.txt", "package.json", "pyproject.toml"]
    found_deps: Dict[str, str] = {}

    for manifest_path in candidates:
        if not manifest_path:
            continue
        try:
            resp = client.get(f"/repos/{repo}/contents/{manifest_path}")
            if resp and "content" in resp:
                content = base64.b64decode(resp["content"]).decode("utf-8", errors="replace")
                if manifest_path.endswith("requirements.txt"):
                    found_deps.update(_parse_requirements_txt(content))
                elif manifest_path.endswith("package.json"):
                    found_deps.update(_parse_package_json(content))
                elif manifest_path.endswith("pyproject.toml"):
                    # Basic extraction for pyproject dependencies
                    in_deps = False
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith("[") and ("dependencies" in line.lower()):
                            in_deps = True
                            continue
                        elif line.startswith("["):
                            in_deps = False
                        if in_deps and "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            found_deps[k.strip().strip('"').strip("'")] = v.strip().strip('"').strip("'")
            if path:
                # If specific path was requested, return after checking it
                break
        except Exception:
            if path:
                # Specified path was not found
                raise
            continue

    return found_deps


def get_stale_branches(
    repo: str,
    days_threshold: int = 30,
    default_branch: Optional[str] = None,
    token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Find branches with no commit activity for more than days_threshold days."""
    client = _get_client(token)
    if not default_branch:
        repo_info = get_repo_info(repo, token=token)
        default_branch = repo_info.get("default_branch", "main")

    branches = client.get(f"/repos/{repo}/branches")
    stale_branches = []
    now = datetime.now(timezone.utc)

    for b in branches:
        b_name = b.get("name")
        if b_name == default_branch:
            continue
        sha = b.get("commit", {}).get("sha")
        if not sha:
            continue

        try:
            commit_data = client.get(f"/repos/{repo}/commits/{sha}")
            date_str = (
                commit_data.get("commit", {}).get("committer", {}).get("date")
                or commit_data.get("commit", {}).get("author", {}).get("date")
            )
            if date_str:
                commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                days_inactive = (now - commit_date).days
                if days_inactive >= days_threshold:
                    stale_branches.append(
                        {
                            "name": b_name,
                            "sha": sha,
                            "last_commit_date": date_str,
                            "days_inactive": days_inactive,
                        }
                    )
        except Exception:
            continue

    return stale_branches


def open_issue(
    repo: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new GitHub issue."""
    client = _get_client(token)
    payload: Dict[str, Any] = {
        "title": title,
        "body": body,
        "labels": labels or ["devops-copilot"],
    }
    return client.post(f"/repos/{repo}/issues", json=payload)


def open_pr(
    repo: str,
    title: str,
    body: str,
    branch: str,
    base: Optional[str] = None,
    changes: Optional[Dict[str, str]] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a branch, optionally commit changes, and open a pull request.

    Never pushes directly to default branch.
    """
    client = _get_client(token)
    if not base:
        repo_info = get_repo_info(repo, token=token)
        base = repo_info.get("default_branch", "main")

    if branch == base:
        raise ValueError(f"Cannot open PR: head branch '{branch}' cannot be identical to base '{base}'.")

    # 1. Get base branch commit SHA
    ref_data = client.get(f"/repos/{repo}/git/ref/heads/{base}")
    base_sha = ref_data.get("object", {}).get("sha")
    if not base_sha:
        raise RuntimeError(f"Could not resolve base branch '{base}' SHA")

    # 2. Create head branch ref
    try:
        client.post(
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
    except Exception as e:
        # Branch might already exist; continue if so
        if "already exists" not in str(e).lower() and "reference already exists" not in str(e).lower():
            raise

    # 3. Commit changes to branch if provided
    if changes:
        for file_path, file_content in changes.items():
            encoded = base64.b64encode(file_content.encode("utf-8")).decode("utf-8")
            put_payload = {
                "message": f"DevOps Copilot: update {file_path}",
                "content": encoded,
                "branch": branch,
            }
            # Check if file exists to provide sha
            try:
                existing = client.get(f"/repos/{repo}/contents/{file_path}", params={"ref": branch})
                if existing and "sha" in existing:
                    put_payload["sha"] = existing["sha"]
            except Exception:
                pass
            client.put(f"/repos/{repo}/contents/{file_path}", json=put_payload)

    # 4. Open Pull Request
    pr_payload = {
        "title": title,
        "body": body,
        "head": branch,
        "base": base,
    }
    return client.post(f"/repos/{repo}/pulls", json=pr_payload)


def get_repo_state(repo: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve full aggregated repo state."""
    info = get_repo_info(repo, token=token)
    default_branch = info.get("default_branch", "main")

    commits = get_commits(repo, limit=5, branch=default_branch, token=token)
    issues = get_issues(repo, state="open", limit=10, token=token)
    prs = get_pull_requests(repo, state="open", limit=10, token=token)
    ci = get_ci_status(repo, branch=default_branch, token=token)
    deps = list_dependencies(repo, token=token)

    return {
        "repo": repo,
        "default_branch": default_branch,
        "description": info.get("description"),
        "recent_commits": commits,
        "open_issues": issues,
        "open_prs": prs,
        "ci_status": ci,
        "dependencies": deps,
    }
