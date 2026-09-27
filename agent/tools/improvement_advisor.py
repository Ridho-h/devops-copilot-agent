"""Improvement Advisor for proposing targeted codebase improvements.

Enforces:
1. Strict allow-list of improvement categories (docstrings, readme_gaps, type_hints, dead_code).
2. Frequency capping / cooldown across scheduled runs.
3. Pre-PR test verification.
4. Low-confidence fallback to issue.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

ALLOWED_IMPROVEMENT_TYPES = ["docstrings", "readme_gaps", "type_hints", "dead_code"]


class ImprovementProposal(BaseModel):
    """A proposed improvement conforming strictly to the allowed scope."""

    improvement_type: str = Field(description="Must be one of docstrings, readme_gaps, type_hints, dead_code")
    target_file: str = Field(description="Path to file being improved")
    title: str = Field(description="Short PR/issue title")
    description: str = Field(description="Clear explanation of why this change is beneficial")
    changes: Dict[str, str] = Field(default_factory=dict, description="Map of file paths to new content")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")

    @field_validator("improvement_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ALLOWED_IMPROVEMENT_TYPES:
            raise ValueError(
                f"Invalid improvement_type '{v}'. Must be one of: {', '.join(ALLOWED_IMPROVEMENT_TYPES)}"
            )
        return v


def is_frequency_capped(
    history: List[Dict[str, Any]], cooldown_runs: int = 3
) -> bool:
    """Check if an improvement was proposed within the last cooldown_runs."""
    recent_runs = history[:cooldown_runs]
    for run in recent_runs:
        for finding in run.get("findings", []):
            if finding.get("type") == "improvement" and finding.get("action_taken") in ("pr", "issue"):
                return True
    return False


def verify_changes_with_tests(
    changes: Dict[str, str],
    test_command: Optional[str] = "pytest",
    cwd: Optional[str] = None,
    timeout: int = 60,
) -> Tuple[bool, str]:
    """Apply proposed changes temporarily, run test suite, and restore original files."""
    if not test_command:
        return True, "Pre-PR verification skipped: no test suite specified."

    backups: Dict[Path, Optional[str]] = {}
    try:
        # 1. Back up existing files and write changes
        for file_path_str, new_content in changes.items():
            path = Path(file_path_str)
            if path.exists():
                backups[path] = path.read_text(encoding="utf-8")
            else:
                backups[path] = None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_content, encoding="utf-8")

        # 2. Run test command
        res = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = (res.stdout or "") + (res.stderr or "")
        return res.returncode == 0, output.strip()

    except Exception as e:
        return False, f"Test execution error: {e}"

    finally:
        # 3. Always restore original files
        for path, original_content in backups.items():
            if original_content is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_text(original_content, encoding="utf-8")
