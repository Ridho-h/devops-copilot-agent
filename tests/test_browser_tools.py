import pytest
from unittest.mock import patch, MagicMock
from agent.tools.browser_tools import (
    check_upstream_changelog,
    search_cve_advisory,
    analyze_changelog_for_breaking_changes,
)


def test_analyze_changelog_for_breaking_changes():
    safe_text = "Version 2.31.0: Fixed memory leak in connection pool, improved error message."
    has_break, kw = analyze_changelog_for_breaking_changes(safe_text)
    assert has_break is False
    assert kw is None

    breaking_text = "Version 3.0.0: BREAKING CHANGE: Removed deprecated v1 API and altered return signature."
    has_break, kw = analyze_changelog_for_breaking_changes(breaking_text)
    assert has_break is True
    assert "breaking" in kw.lower()


@patch("agent.tools.browser_tools.requests.get")
def test_check_upstream_changelog_safe(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """
    <html>
      <body>
        <div class="project-description">
          <h2>Release 2.31.0</h2>
          <p>Bug fixes and performance improvements.</p>
        </div>
      </body>
    </html>
    """
    mock_resp.json.return_value = {
        "info": {"version": "2.31.0", "project_urls": {"Changelog": "https://github.com/psf/requests/releases"}}
    }
    mock_get.return_value = mock_resp

    result = check_upstream_changelog("requests", current_version="2.30.0", target_version="2.31.0")
    assert result["package"] == "requests"
    assert result["has_breaking_changes"] is False
    assert result["is_safe_to_bump"] is True


@patch("agent.tools.browser_tools.requests.get")
def test_check_upstream_changelog_breaking(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """
    <html>
      <body>
        <div class="release">
          <h2>3.0.0</h2>
          <p>BREAKING CHANGE: dropped python 3.8 support and removed legacy client.</p>
        </div>
      </body>
    </html>
    """
    mock_resp.json.return_value = {
        "info": {"version": "3.0.0"}
    }
    mock_get.return_value = mock_resp

    result = check_upstream_changelog("example-lib", current_version="2.0.0", target_version="3.0.0")
    assert result["has_breaking_changes"] is True
    assert result["is_safe_to_bump"] is False


@patch("agent.tools.browser_tools.requests.post")
def test_search_cve_advisory_found(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "vulns": [
            {
                "id": "GHSA-j8r2-6x86-q33q",
                "aliases": ["CVE-2023-32681"],
                "summary": "Requests Proxy-Authorization Header Leak in redirect",
                "database_specific": {"severity": "HIGH"},
                "affected": [
                    {
                        "ranges": [
                            {
                                "events": [
                                    {"introduced": "0"},
                                    {"fixed": "2.31.0"}
                                ]
                            }
                        ]
                    }
                ],
            }
        ]
    }
    mock_post.return_value = mock_resp

    vulns = search_cve_advisory("requests", version="2.30.0")
    assert len(vulns) == 1
    assert vulns[0]["cve_id"] == "CVE-2023-32681"
    assert vulns[0]["severity"] == "HIGH"
    assert vulns[0]["fixed_version"] == "2.31.0"


@patch("agent.tools.browser_tools.requests.post")
def test_search_cve_advisory_none(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {}
    mock_post.return_value = mock_resp

    vulns = search_cve_advisory("requests", version="2.31.0")
    assert len(vulns) == 0
