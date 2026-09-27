import pytest
from unittest.mock import patch, MagicMock
from agent.tools.improvement_advisor import (
    ALLOWED_IMPROVEMENT_TYPES,
    ImprovementProposal,
    is_frequency_capped,
    verify_changes_with_tests,
)


def test_allowed_improvement_types():
    assert "docstrings" in ALLOWED_IMPROVEMENT_TYPES
    assert "readme_gaps" in ALLOWED_IMPROVEMENT_TYPES
    assert "type_hints" in ALLOWED_IMPROVEMENT_TYPES
    assert "dead_code" in ALLOWED_IMPROVEMENT_TYPES
    assert "architecture_refactor" not in ALLOWED_IMPROVEMENT_TYPES


def test_improvement_proposal_validation():
    valid = ImprovementProposal(
        improvement_type="docstrings",
        target_file="agent/tools/github_tools.py",
        title="Add missing docstrings to github_tools.py",
        description="Improves code readability by documenting return values",
        changes={"agent/tools/github_tools.py": "def foo():\n    '''New docstring'''\n    pass"},
        confidence=0.9,
    )
    assert valid.improvement_type == "docstrings"

    with pytest.raises(ValueError, match="Invalid improvement_type"):
        ImprovementProposal(
            improvement_type="massive_refactor",
            target_file="agent/orchestrator.py",
            title="Rewrite engine",
            description="Open ended refactor",
            changes={},
            confidence=0.5,
        )


def test_is_frequency_capped():
    # Cooldown of 3 runs. Last run had an improvement -> capped
    recent_history = [
        {"findings": [{"type": "improvement", "action_taken": "pr"}]},
        {"findings": []},
    ]
    assert is_frequency_capped(recent_history, cooldown_runs=3) is True

    # No improvement in recent history -> not capped
    clean_history = [
        {"findings": []},
        {"findings": []},
        {"findings": []},
    ]
    assert is_frequency_capped(clean_history, cooldown_runs=3) is False


def test_verify_changes_with_tests_success(tmp_path):
    test_file = tmp_path / "hello.py"
    test_file.write_text("def hello(): return 'original'")

    changes = {str(test_file): "def hello(): return 'updated'"}

    with patch("agent.tools.improvement_advisor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="1 passed in 0.1s", stderr="")
        passed, msg = verify_changes_with_tests(changes, test_command="pytest")

        assert passed is True
        assert "passed" in msg
        # File should be restored after verification
        assert test_file.read_text() == "def hello(): return 'original'"


def test_verify_changes_with_tests_failure(tmp_path):
    test_file = tmp_path / "hello.py"
    test_file.write_text("def hello(): return 'original'")

    changes = {str(test_file): "def hello(): return 'broken syntax'"}

    with patch("agent.tools.improvement_advisor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="SyntaxError", stderr="")
        passed, msg = verify_changes_with_tests(changes, test_command="pytest")

        assert passed is False
        assert "SyntaxError" in msg
        # File should still be safely restored
        assert test_file.read_text() == "def hello(): return 'original'"


def test_verify_changes_no_test_command(tmp_path):
    passed, msg = verify_changes_with_tests({}, test_command=None)
    assert passed is True
    assert "skipped" in msg.lower() or "no test" in msg.lower()
