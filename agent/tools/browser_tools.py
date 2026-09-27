"""Browser and RPA tools for upstream changelogs and CVE advisories.

Provides:
- check_upstream_changelog: Playwright-powered (with HTTP fallback) release note and breaking change inspection.
- search_cve_advisory: Security vulnerability intelligence via OSV.dev and advisory registries.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
import requests

try:
    from playwright.sync_api import sync_playwright  # type: ignore

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


BREAKING_KEYWORDS = [
    "breaking change",
    "breaking changes",
    "backward incompatible",
    "backwards incompatible",
    "migration guide",
    "deprecated and removed",
    "removed deprecated",
    "dropped python",
    "no longer supported",
]


def analyze_changelog_for_breaking_changes(text: str) -> Tuple[bool, Optional[str]]:
    """Scan changelog text for signs of breaking changes or migration hurdles."""
    text_lower = text.lower()
    for kw in BREAKING_KEYWORDS:
        if kw in text_lower:
            return True, kw
    return False, None


def _fetch_page_with_playwright(url: str, timeout: int = 15000) -> Optional[str]:
    """Fetch rendered page HTML using Playwright headless Chromium."""
    if not HAS_PLAYWRIGHT:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout)
            content = page.content()
            browser.close()
            return content
    except Exception:
        return None


def check_upstream_changelog(
    package: str,
    current_version: str,
    target_version: Optional[str] = None,
    use_browser: bool = False,
) -> Dict[str, Any]:
    """Check upstream changelog for release notes and breaking changes."""
    url = f"https://pypi.org/pypi/{package}/json"
    changelog_text = ""
    target_v = target_version
    changelog_url = None

    try:
        resp = requests.get(url, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            info = data.get("info", {})
            if not target_v:
                target_v = info.get("version", current_version)

            project_urls = info.get("project_urls") or {}
            for k, u in project_urls.items():
                if any(term in k.lower() for term in ["changelog", "release", "changes", "history"]):
                    changelog_url = u
                    break

            changelog_text = info.get("description") or resp.text
        else:
            changelog_text = resp.text
    except Exception:
        pass

    # If Playwright is requested and a changelog URL is available, try browser scraping
    if use_browser and changelog_url and HAS_PLAYWRIGHT:
        rendered = _fetch_page_with_playwright(changelog_url)
        if rendered:
            changelog_text = rendered

    has_breaking, keyword = analyze_changelog_for_breaking_changes(changelog_text)

    is_safe = not has_breaking
    summary = (
        f"Found potential breaking changes ('{keyword}') in release notes"
        if has_breaking
        else "No breaking changes detected in release notes"
    )

    return {
        "package": package,
        "current_version": current_version,
        "target_version": target_v,
        "has_breaking_changes": has_breaking,
        "breaking_keyword": keyword,
        "is_safe_to_bump": is_safe,
        "summary": summary,
        "changelog_url": changelog_url,
    }


def search_cve_advisory(
    package: str,
    version: str,
    ecosystem: str = "PyPI",
) -> List[Dict[str, Any]]:
    """Search for known security vulnerabilities (CVEs / GHSA) affecting a package version."""
    url = "https://api.osv.dev/v1/query"
    payload = {
        "package": {
            "name": package,
            "ecosystem": ecosystem,
        },
        "version": version,
    }

    advisories: List[Dict[str, Any]] = []

    try:
        resp = requests.post(url, json=payload, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            vulns = data.get("vulns", [])
            for v in vulns:
                aliases = v.get("aliases", [])
                cve_id = next((a for a in aliases if a.startswith("CVE-")), None) or v.get("id")

                severity = "UNKNOWN"
                db_specific = v.get("database_specific") or {}
                if "severity" in db_specific:
                    severity = db_specific["severity"]
                elif v.get("severity"):
                    severity = v["severity"][0].get("score", "UNKNOWN")

                # Find fixed version if specified in ranges
                fixed_ver = None
                for affected in v.get("affected", []):
                    for r in affected.get("ranges", []):
                        for event in r.get("events", []):
                            if "fixed" in event:
                                fixed_ver = event["fixed"]
                                break

                advisories.append(
                    {
                        "id": v.get("id"),
                        "cve_id": cve_id,
                        "summary": v.get("summary") or v.get("details", "")[:120],
                        "severity": severity,
                        "affected_version": version,
                        "fixed_version": fixed_ver,
                        "advisory_url": f"https://osv.dev/vulnerability/{v.get('id')}",
                    }
                )
    except Exception:
        pass

    return advisories
