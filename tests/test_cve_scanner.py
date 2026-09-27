import pytest
from unittest.mock import patch
from agent.tools.cve_scanner import (
    is_at_least_medium,
    scan_dependencies_for_cves,
)


def test_is_at_least_medium():
    assert is_at_least_medium("CRITICAL") is True
    assert is_at_least_medium("HIGH") is True
    assert is_at_least_medium("MODERATE") is True
    assert is_at_least_medium("MEDIUM") is True
    assert is_at_least_medium("LOW") is False
    assert is_at_least_medium("UNKNOWN") is False


@patch("agent.tools.cve_scanner.search_cve_advisory")
def test_severity_filtering_and_deduplication(mock_search):
    mock_search.return_value = [
        {
            "id": "GHSA-1",
            "cve_id": "CVE-2023-0001",
            "summary": "Low severity issue",
            "severity": "LOW",
            "affected_version": "2.25.0",
            "fixed_version": "2.26.0",
            "advisory_url": "https://osv.dev/1",
        },
        {
            "id": "GHSA-2",
            "cve_id": "CVE-2023-0002",
            "summary": "High severity issue",
            "severity": "HIGH",
            "affected_version": "2.25.0",
            "fixed_version": "2.31.0",
            "advisory_url": "https://osv.dev/2",
        },
        {
            "id": "GHSA-3",
            "cve_id": "CVE-2023-0003",
            "summary": "Moderate severity issue",
            "severity": "MODERATE",
            "affected_version": "2.25.0",
            "fixed_version": "2.28.0",
            "advisory_url": "https://osv.dev/3",
        },
    ]

    deps = {"requests": "==2.25.0"}
    cve_findings = scan_dependencies_for_cves(deps)

    assert "requests" in cve_findings
    req_summary = cve_findings["requests"]
    # LOW must be filtered out, leaving 2 (HIGH and MODERATE)
    assert len(req_summary["advisories"]) == 2
    assert req_summary["highest_severity"] == "HIGH"
    # Deduplication into single record per package
    assert req_summary["current_version"] == "2.25.0"
    assert req_summary["recommended_fix"] == "2.31.0"


@patch("agent.tools.cve_scanner.search_cve_advisory")
def test_scan_dependencies_clean(mock_search):
    mock_search.return_value = []
    deps = {"requests": "==2.32.4"}
    cve_findings = scan_dependencies_for_cves(deps)
    assert cve_findings == {}
