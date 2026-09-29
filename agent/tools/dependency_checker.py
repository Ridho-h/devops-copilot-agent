"""Outdated dependency detection for DevOps Copilot Agent."""

import re
from typing import Any, Dict, List, Optional
import requests
from packaging import version


def parse_version_spec(spec: str) -> Optional[str]:
    """Extract a clean semver string from a dependency specification."""
    if not spec or spec == "*":
        return None

    # Strip prefixes like ==, >=, <=, ~=, ^, ~, v
    cleaned = spec.strip().lstrip("^~=<>v")
    # Take first token before any comma/semicolon or space
    cleaned = re.split(r"[,;\s]", cleaned)[0].strip()

    if not cleaned:
        return None

    try:
        # Validate that it parses as a version
        version.parse(cleaned)
        return cleaned
    except Exception:
        return None


def fetch_pypi_latest(package: str, timeout: float = 3.0) -> Optional[str]:
    """Fetch the latest published version of a Python package from PyPI."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("info", {}).get("version")
    except Exception:
        pass
    return None


def fetch_npm_latest(package: str, timeout: float = 3.0) -> Optional[str]:
    """Fetch the latest published version of an npm package."""
    url = f"https://registry.npmjs.org/{package}/latest"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("version")
    except Exception:
        pass
    return None


def check_outdated_dependencies(
    dependencies: Dict[str, str], max_checks: int = 20
) -> List[Dict[str, Any]]:
    """Check dependencies against registries to identify outdated versions."""
    outdated: List[Dict[str, Any]] = []
    checked_count = 0

    for pkg_name, spec in dependencies.items():
        if checked_count >= max_checks:
            break

        current_ver_str = parse_version_spec(spec)
        if not current_ver_str:
            continue

        checked_count += 1
        # Try PyPI first, then npm
        latest_ver_str = fetch_pypi_latest(pkg_name)
        if not latest_ver_str:
            latest_ver_str = fetch_npm_latest(pkg_name)

        if not latest_ver_str:
            continue

        try:
            current_v = version.parse(current_ver_str)
            latest_v = version.parse(latest_ver_str)
            if latest_v > current_v:
                outdated.append(
                    {
                        "package": pkg_name,
                        "current_version": current_ver_str,
                        "latest_version": latest_ver_str,
                        "is_outdated": True,
                    }
                )
        except Exception:
            continue

    return outdated
