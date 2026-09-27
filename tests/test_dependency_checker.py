import pytest
from unittest.mock import patch, MagicMock
from agent.tools.dependency_checker import check_outdated_dependencies, parse_version_spec


def test_parse_version_spec():
    assert parse_version_spec("==2.25.0") == "2.25.0"
    assert parse_version_spec(">=1.0.0") == "1.0.0"
    assert parse_version_spec("^4.18.2") == "4.18.2"
    assert parse_version_spec("~=0.1.2") == "0.1.2"
    assert parse_version_spec("*") is None
    assert parse_version_spec("") is None


@patch("agent.tools.dependency_checker.requests.get")
def test_check_outdated_dependencies_pypi(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "info": {
            "version": "2.31.0"
        }
    }
    mock_get.return_value = mock_resp

    deps = {"requests": "==2.25.0"}
    outdated = check_outdated_dependencies(deps)

    assert len(outdated) == 1
    assert outdated[0]["package"] == "requests"
    assert outdated[0]["current_version"] == "2.25.0"
    assert outdated[0]["latest_version"] == "2.31.0"
    assert outdated[0]["is_outdated"] is True


@patch("agent.tools.dependency_checker.requests.get")
def test_check_outdated_dependencies_already_latest(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "info": {
            "version": "2.31.0"
        }
    }
    mock_get.return_value = mock_resp

    deps = {"requests": "==2.31.0"}
    outdated = check_outdated_dependencies(deps)

    assert len(outdated) == 0


@patch("agent.tools.dependency_checker.requests.get")
def test_check_outdated_dependencies_handles_unpinned_and_errors(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    deps = {"unknown-pkg-xyz": "==1.0.0", "unpinned-pkg": "*"}
    outdated = check_outdated_dependencies(deps)

    assert len(outdated) == 0
