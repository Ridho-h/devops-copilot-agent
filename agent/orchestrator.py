"""DevOps Copilot Orchestrator — Core Decision Loop."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is in sys.path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from agent.tools.github_tools import (
    get_repo_state,
    get_stale_branches,
    open_issue,
    open_pr,
)
from agent.tools.dependency_checker import check_outdated_dependencies
from agent.tools.cve_scanner import scan_dependencies_for_cves
from agent.tools.improvement_advisor import (
    ALLOWED_IMPROVEMENT_TYPES,
    ImprovementProposal,
    is_frequency_capped,
    verify_changes_with_tests,
)

load_dotenv()


class RunFinding(BaseModel):
    type: str = Field(description="Type of finding: ci_failure, stale_branches, dependency_risk, improvement, or none")
    evidence: str = Field(description="Evidence collected and cited for this finding")
    action_taken: str = Field(description="Action taken: issue, pr, or none")
    reference: Optional[str] = Field(default=None, description="URL or reference to opened issue or PR")


class RunSummary(BaseModel):
    run_date: str
    repo: str
    findings: List[RunFinding] = Field(default_factory=list)
    summary: str


class DevOpsOrchestrator:
    """Scheduled orchestrator agent for repository maintenance."""

    def __init__(
        self,
        repo: Optional[str] = None,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        log_path: str = "agent/run_log.json",
        prompt_path: Optional[str] = None,
        model_name: str = "gemini-1.5-flash",
        dry_run: bool = False,
    ):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY") or ""
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.log_path = Path(log_path)
        self.model_name = model_name
        self.dry_run = dry_run

        if prompt_path:
            self.prompt_path = Path(prompt_path)
        else:
            default_prompt = Path(__file__).parent / "prompts" / "orchestrator_prompt.md"
            if not default_prompt.exists():
                default_prompt = Path(__file__).parent / "prompts" / "RULES.md"
            self.prompt_path = default_prompt

        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        if self.prompt_path and self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return "DevOps Copilot Orchestrator Prompt"

    def _load_run_history(self) -> List[Dict[str, Any]]:
        """Load recent run logs for frequency capping and auditability."""
        if not self.log_path.exists():
            return []
        try:
            content = self.log_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
        except Exception:
            pass
        return []

    def _check_duplicate_issue(self, open_issues: List[Dict[str, Any]], keywords: List[str]) -> Optional[Dict[str, Any]]:
        """Check if an open issue already addresses this finding to prevent spam."""
        for issue in open_issues:
            title_lower = issue.get("title", "").lower()
            if all(kw.lower() in title_lower for kw in keywords):
                return issue
        return None

    def decide(
        self,
        repo_state: Dict[str, Any],
        stale_branches: List[Dict[str, Any]],
        outdated_deps: Optional[List[Dict[str, Any]]] = None,
        candidate_improvement: Optional[ImprovementProposal] = None,
        cve_findings: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[List[RunFinding], str]:
        """Core decision loop following orchestrator rules."""
        findings: List[RunFinding] = []
        open_issues = repo_state.get("open_issues", [])
        ci_status = repo_state.get("ci_status", {})
        default_branch = repo_state.get("default_branch", "main")

        # 1. CI Health Check (Highest Priority)
        if ci_status.get("status") == "failing":
            failing_runs = ci_status.get("failing_runs", [])
            latest_run = failing_runs[0] if failing_runs else {}
            run_name = latest_run.get("name", "CI Workflow")
            run_url = latest_run.get("html_url", "GitHub Actions")
            run_id = latest_run.get("id", "latest")

            existing = self._check_duplicate_issue(open_issues, ["CI failing", default_branch])
            if existing:
                findings.append(
                    RunFinding(
                        type="ci_failure",
                        evidence=f"CI is failing on {default_branch} (Run #{run_id}), but an issue is already open: #{existing.get('number')} ({existing.get('title')})",
                        action_taken="none",
                        reference=existing.get("html_url"),
                    )
                )
                return findings, f"CI failure detected on {default_branch}, but already tracked in issue #{existing.get('number')}."
            else:
                issue_title = f"CI failing on {default_branch} ({run_name})"
                issue_body = (
                    f"## DevOps Copilot Health Report: CI Failure Detected\n\n"
                    f"**Evidence:**\n"
                    f"- **Branch:** `{default_branch}`\n"
                    f"- **Workflow:** `{run_name}`\n"
                    f"- **Run ID:** `{run_id}`\n"
                    f"- **Run Link:** [{run_name} Run #{run_id}]({run_url})\n"
                    f"- **Conclusion:** `{latest_run.get('conclusion', 'failure')}`\n\n"
                    f"Please investigate the failing CI checks before merging new changes."
                )
                if self.dry_run:
                    findings.append(
                        RunFinding(
                            type="ci_failure",
                            evidence=f"[DRY RUN] Would open issue for failing CI: {issue_title}",
                            action_taken="dry_run_issue",
                            reference=f"dry_run://{self.repo}/issues/{issue_title}",
                        )
                    )
                    return findings, f"[DRY RUN] Would open issue: {issue_title}"

                created_issue = open_issue(
                    repo=self.repo,
                    title=issue_title,
                    body=issue_body,
                    labels=["devops-copilot", "ci-failure"],
                    token=self.token,
                )
                findings.append(
                    RunFinding(
                        type="ci_failure",
                        evidence=f"Latest CI workflow run #{run_id} failed on {default_branch}: {run_url}",
                        action_taken="issue",
                        reference=created_issue.get("html_url"),
                    )
                )
                return findings, f"Opened issue #{created_issue.get('number')} for CI failure on {default_branch}."

        # 2. CVE Advisory Check (Security Risk: ranks ahead of stale branches and routine maintenance)
        if cve_findings:
            pkg_name, cve_info = next(iter(cve_findings.items()))
            existing = self._check_duplicate_issue(open_issues, ["security vulnerability", pkg_name])
            if existing:
                findings.append(
                    RunFinding(
                        type="cve_advisory",
                        evidence=f"Security vulnerability in {pkg_name} detected, but already tracked in issue #{existing.get('number')}",
                        action_taken="none",
                        reference=existing.get("html_url"),
                    )
                )
                return findings, f"Security vulnerability in {pkg_name} already tracked in issue #{existing.get('number')}."
            else:
                adv_rows = "\n".join(
                    [
                        f"| [{a.get('cve_id')}]({a.get('advisory_url')}) | `{a.get('severity')}` | {a.get('summary')} | `{a.get('fixed_version') or 'Not specified'}` |"
                        for a in cve_info.get("advisories", [])
                    ]
                )
                issue_title = f"Security vulnerability in {pkg_name} ({cve_info.get('highest_severity')})"
                issue_body = (
                    f"## DevOps Copilot Security Alert: Vulnerability in `{pkg_name}`\n\n"
                    f"A confirmed security vulnerability of **{cve_info.get('highest_severity')}** severity was detected in `{pkg_name}` (installed: `{cve_info.get('current_version')}`).\n\n"
                    f"### Recommended Action\n"
                    f"Update `{pkg_name}` to version `{cve_info.get('recommended_fix') or 'latest'}` or higher.\n\n"
                    f"### Detected Advisories ({len(cve_info.get('advisories', []))} total)\n\n"
                    f"| Advisory / CVE | Severity | Summary | Fixed In |\n"
                    f"| :--- | :--- | :--- | :--- |\n"
                    f"{adv_rows}\n"
                )
                if self.dry_run:
                    findings.append(
                        RunFinding(
                            type="cve_advisory",
                            evidence=f"[DRY RUN] Would open security issue for {pkg_name}: {cve_info.get('highest_severity')} ({len(cve_info.get('advisories', []))} advisories)",
                            action_taken="dry_run_issue",
                            reference=f"dry_run://{self.repo}/issues/{issue_title}",
                        )
                    )
                    return findings, f"[DRY RUN] Would open security issue: {issue_title}"

                created_issue = open_issue(
                    repo=self.repo,
                    title=issue_title,
                    body=issue_body,
                    labels=["devops-copilot", "security", "cve"],
                    token=self.token,
                )
                cve_ids_str = ", ".join(a.get("cve_id", a.get("id")) for a in cve_info.get("advisories", []))
                findings.append(
                    RunFinding(
                        type="cve_advisory",
                        evidence=f"Confirmed security advisory in {pkg_name} ({cve_info.get('highest_severity')}): {cve_ids_str}",
                        action_taken="issue",
                        reference=created_issue.get("html_url"),
                    )
                )
                return findings, f"Opened security issue #{created_issue.get('number')} for {pkg_name} ({cve_info.get('highest_severity')})."

        # 3. Stale Branches Check
        if stale_branches:
            existing = self._check_duplicate_issue(open_issues, ["stale branches"])
            if existing:
                findings.append(
                    RunFinding(
                        type="stale_branches",
                        evidence=f"Found {len(stale_branches)} stale branch(es), but already tracked in issue #{existing.get('number')}",
                        action_taken="none",
                        reference=existing.get("html_url"),
                    )
                )
                return findings, f"Stale branches detected, but already tracked in issue #{existing.get('number')}."
            else:
                branch_lines = "\n".join(
                    [
                        f"- `{b['name']}` (last commit {b.get('last_commit_date', 'unknown')}, {b.get('days_inactive')} days inactive)"
                        for b in stale_branches
                    ]
                )
                issue_title = "Stale branches detected (>30 days inactive)"
                issue_body = (
                    f"## DevOps Copilot Maintenance: Stale Branches\n\n"
                    f"The following branch(es) have had no commit activity for 30+ days and are not merged into `{default_branch}`:\n\n"
                    f"{branch_lines}\n\n"
                    f"Consider deleting these branches if they are no longer needed."
                )
                if self.dry_run:
                    findings.append(
                        RunFinding(
                            type="stale_branches",
                            evidence=f"[DRY RUN] Would open issue for {len(stale_branches)} stale branch(es)",
                            action_taken="dry_run_issue",
                            reference=f"dry_run://{self.repo}/issues/{issue_title}",
                        )
                    )
                    return findings, f"[DRY RUN] Would open issue: {issue_title}"

                created_issue = open_issue(
                    repo=self.repo,
                    title=issue_title,
                    body=issue_body,
                    labels=["devops-copilot", "maintenance"],
                    token=self.token,
                )
                findings.append(
                    RunFinding(
                        type="stale_branches",
                        evidence=f"{len(stale_branches)} branch(es) inactive for >30 days: {', '.join(b['name'] for b in stale_branches)}",
                        action_taken="issue",
                        reference=created_issue.get("html_url"),
                    )
                )
                return findings, f"Opened issue #{created_issue.get('number')} for {len(stale_branches)} stale branch(es)."

        # 4. Outdated Dependencies Check (with CVE overlap exclusion)
        # Rule: if package has both a pending version bump and a known CVE, skip the separate outdated issue
        filtered_outdated = [
            d for d in (outdated_deps or [])
            if not cve_findings or d["package"] not in cve_findings
        ]
        if filtered_outdated:
            existing = self._check_duplicate_issue(open_issues, ["outdated dependencies"])
            if existing:
                findings.append(
                    RunFinding(
                        type="outdated_dependencies",
                        evidence=f"Found {len(filtered_outdated)} outdated dependency(ies), but already tracked in issue #{existing.get('number')}",
                        action_taken="none",
                        reference=existing.get("html_url"),
                    )
                )
                return findings, f"Outdated dependencies detected, but already tracked in issue #{existing.get('number')}."
            else:
                dep_table_rows = "\n".join(
                    [
                        f"| `{d['package']}` | `{d['current_version']}` | `{d['latest_version']}` |"
                        for d in filtered_outdated
                    ]
                )
                issue_title = f"Outdated dependencies detected ({len(filtered_outdated)} package(s))"
                issue_body = (
                    f"## DevOps Copilot Health Report: Outdated Dependencies\n\n"
                    f"The following dependencies are pinned behind their latest versions:\n\n"
                    f"| Package | Current Version | Latest Version |\n"
                    f"| :--- | :--- | :--- |\n"
                    f"{dep_table_rows}\n\n"
                    f"Consider testing and updating these packages to receive bug fixes, improvements, and security patches."
                )
                if self.dry_run:
                    findings.append(
                        RunFinding(
                            type="outdated_dependencies",
                            evidence=f"[DRY RUN] Would open issue for {len(filtered_outdated)} outdated dependency(ies): {', '.join(d['package'] for d in filtered_outdated)}",
                            action_taken="dry_run_issue",
                            reference=f"dry_run://{self.repo}/issues/{issue_title}",
                        )
                    )
                    return findings, f"[DRY RUN] Would open issue: {issue_title}"

                created_issue = open_issue(
                    repo=self.repo,
                    title=issue_title,
                    body=issue_body,
                    labels=["devops-copilot", "dependencies"],
                    token=self.token,
                )
                dep_details = ", ".join(
                    f"{d['package']} ({d['current_version']} -> {d['latest_version']})"
                    for d in filtered_outdated
                )
                findings.append(
                    RunFinding(
                        type="outdated_dependencies",
                        evidence=f"{len(filtered_outdated)} dependency(ies) outdated: {dep_details}",
                        action_taken="issue",
                        reference=created_issue.get("html_url"),
                    )
                )
                return findings, f"Opened issue #{created_issue.get('number')} for {len(filtered_outdated)} outdated dependency(ies)."

        # 4. Improvement Suggestion Task (Constrained Scope, Frequency Capped, Pre-PR Verified)
        if candidate_improvement:
            # Frequency Cap Guardrail: Checks both live GitHub PRs and local history
            history = self._load_run_history()
            recent_prs = repo_state.get("open_prs", [])
            if is_frequency_capped(history=history, recent_prs=recent_prs, cooldown_days=14, cooldown_runs=3):
                # Frequency capped: skip to avoid flooding
                pass
            else:
                # Pre-PR Test Verification Guardrail
                passed, test_output = verify_changes_with_tests(candidate_improvement.changes)

                # High-Confidence Gate
                if passed and candidate_improvement.confidence >= 0.8:
                    branch_name = f"devops-copilot/{candidate_improvement.improvement_type}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                    pr_body = (
                        f"## DevOps Copilot Improvement: {candidate_improvement.title}\n\n"
                        f"**Category:** `{candidate_improvement.improvement_type}`\n"
                        f"**Target File:** `{candidate_improvement.target_file}`\n\n"
                        f"### Why This Change Was Proposed\n{candidate_improvement.description}\n\n"
                        f"### Pre-PR Verification\n- [x] Local test suite ran against changes and passed.\n"
                    )
                    if self.dry_run:
                        findings.append(
                            RunFinding(
                                type="improvement",
                                evidence=f"[DRY RUN] Would open PR for {candidate_improvement.title}",
                                action_taken="dry_run_pr",
                                reference=f"dry_run://{self.repo}/pulls/{candidate_improvement.title}",
                            )
                        )
                        return findings, f"[DRY RUN] Would open PR: {candidate_improvement.title}"

                    created_pr = open_pr(
                        repo=self.repo,
                        title=candidate_improvement.title,
                        body=pr_body,
                        branch=branch_name,
                        base=default_branch,
                        changes=candidate_improvement.changes,
                        token=self.token,
                    )
                    findings.append(
                        RunFinding(
                            type="improvement",
                            evidence=f"Proposed {candidate_improvement.improvement_type} in {candidate_improvement.target_file} (tests verified)",
                            action_taken="pr",
                            reference=created_pr.get("html_url"),
                        )
                    )
                    return findings, f"Opened PR #{created_pr.get('number')} for {candidate_improvement.improvement_type}."

                else:
                    # Low-Confidence Fallback Rule: Open an issue, NEVER open a broken/unconfident PR
                    issue_title = f"[Suggestion] {candidate_improvement.title}"
                    issue_body = (
                        f"## DevOps Copilot Improvement Suggestion\n\n"
                        f"**Category:** `{candidate_improvement.improvement_type}`\n"
                        f"**Target File:** `{candidate_improvement.target_file}`\n"
                        f"**Confidence:** `{candidate_improvement.confidence:.2f}`\n\n"
                        f"### Description\n{candidate_improvement.description}\n\n"
                        f"### Pre-PR Verification Status\n"
                        f"A pull request was **not** opened due to safety guardrails:\n"
                        f"- Tests passed: `{passed}`\n"
                        f"- Test details: `{test_output}`\n\n"
                        f"Please review this suggestion manually."
                    )
                    if self.dry_run:
                        findings.append(
                            RunFinding(
                                type="improvement",
                                evidence=f"[DRY RUN] Low confidence fallback: would open issue for {candidate_improvement.title}",
                                action_taken="dry_run_issue",
                                reference=f"dry_run://{self.repo}/issues/{issue_title}",
                            )
                        )
                        return findings, f"[DRY RUN] Would open suggestion issue (fallback): {issue_title}"

                    created_issue = open_issue(
                        repo=self.repo,
                        title=issue_title,
                        body=issue_body,
                        labels=["devops-copilot", "improvement-suggestion"],
                        token=self.token,
                    )
                    findings.append(
                        RunFinding(
                            type="improvement",
                            evidence=f"Pre-PR verification tests failed or low confidence ({candidate_improvement.confidence}): {test_output}",
                            action_taken="issue",
                            reference=created_issue.get("html_url"),
                        )
                    )
                    return findings, f"Opened suggestion issue #{created_issue.get('number')} (fallback) for {candidate_improvement.improvement_type}."

        # 5. Quiet run: No action needed
        summary_msg = "No action needed this run. Repository is healthy."
        return findings, summary_msg

    def run(self, candidate_improvement: Optional[ImprovementProposal] = None) -> RunSummary:
        """Execute one complete orchestrator cycle."""
        now_str = datetime.now(timezone.utc).isoformat()
        if not self.repo:
            raise ValueError("Repository not specified. Set GITHUB_REPOSITORY or pass repo parameter.")

        # 1. Fetch current repository state
        repo_state = get_repo_state(self.repo, token=self.token)
        stale_branches = get_stale_branches(
            self.repo,
            days_threshold=30,
            default_branch=repo_state.get("default_branch"),
            token=self.token,
        )
        dependencies = repo_state.get("dependencies", {})
        cve_findings = scan_dependencies_for_cves(dependencies)
        outdated_deps = check_outdated_dependencies(dependencies)

        # 2. Run decision loop
        findings, summary_text = self.decide(
            repo_state,
            stale_branches,
            outdated_deps=outdated_deps,
            candidate_improvement=candidate_improvement,
            cve_findings=cve_findings,
        )

        summary = RunSummary(
            run_date=now_str,
            repo=self.repo,
            findings=findings,
            summary=summary_text,
        )

        # 3. Write run log for auditability (scheduled-run.yml artifact)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")

        return summary


def main():
    import argparse

    parser = argparse.ArgumentParser(description="DevOps Copilot Orchestrator")
    parser.add_argument("repo", nargs="?", help="Repository in 'owner/repo' format (or env GITHUB_REPOSITORY)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without modifying repository")
    args = parser.parse_args()

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY")

    if not repo:
        parser.print_help()
        sys.exit(1)

    orchestrator = DevOpsOrchestrator(repo=repo, dry_run=args.dry_run)
    summary = orchestrator.run()
    print(f"Run Date: {summary.run_date}")
    print(f"Repo:     {summary.repo}")
    print(f"Summary:  {summary.summary}")
    print(f"Findings: {len(summary.findings)}")
    for f in summary.findings:
        print(f"  - [{f.type}] Action: {f.action_taken} | Ref: {f.reference}")
        print(f"    Evidence: {f.evidence}")


if __name__ == "__main__":
    main()
