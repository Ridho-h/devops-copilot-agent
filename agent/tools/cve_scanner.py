"""CVE scanning and advisory aggregation with severity filtering and deduplication."""

from typing import Any, Dict, List, Optional
from packaging import version as pkg_version

from agent.tools.browser_tools import search_cve_advisory
from agent.tools.dependency_checker import parse_version_spec

SEVERITY_WEIGHTS = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MODERATE": 2,
    "MEDIUM": 2,
    "LOW": 1,
    "UNKNOWN": 0,
}


def is_at_least_medium(severity: str) -> bool:
    """Return True if severity is MEDIUM/MODERATE, HIGH, or CRITICAL."""
    if not severity:
        return False
    return SEVERITY_WEIGHTS.get(severity.upper(), 0) >= 2


def _resolve_best_fixed_version(advisories: List[Dict[str, Any]]) -> Optional[str]:
    """Find the highest fixed version recommended across advisories."""
    fixed_versions = []
    for a in advisories:
        fv = a.get("fixed_version")
        if fv:
            try:
                fixed_versions.append((pkg_version.parse(fv), fv))
            except Exception:
                fixed_versions.append((None, fv))

    if not fixed_versions:
        return None

    # Sort parsed semver versions to pick the highest fix
    valid_parsed = [item for item in fixed_versions if item[0] is not None]
    if valid_parsed:
        valid_parsed.sort(key=lambda x: x[0], reverse=True)
        return valid_parsed[0][1]

    return fixed_versions[0][1]


def scan_dependencies_for_cves(
    dependencies: Dict[str, str],
    min_severity: str = "MEDIUM",
) -> Dict[str, Dict[str, Any]]:
    """Scan dependencies for security vulnerabilities with severity filtering and package dedup."""
    results: Dict[str, Dict[str, Any]] = {}

    for package_name, spec in dependencies.items():
        ver_str = parse_version_spec(spec)
        if not ver_str:
            continue

        advisories = search_cve_advisory(package_name, ver_str)
        if not advisories:
            continue

        # Severity filtering: medium or above only
        filtered_advisories = [
            a for a in advisories if is_at_least_medium(a.get("severity", ""))
        ]

        if not filtered_advisories:
            continue

        # Deduplicate all CVEs for this package into a single entry
        highest_sev = max(
            filtered_advisories,
            key=lambda x: SEVERITY_WEIGHTS.get(x.get("severity", "").upper(), 0),
        ).get("severity", "MEDIUM")

        best_fix = _resolve_best_fixed_version(filtered_advisories)

        results[package_name] = {
            "package": package_name,
            "current_version": ver_str,
            "highest_severity": highest_sev,
            "recommended_fix": best_fix,
            "advisories": filtered_advisories,
        }

    return results
