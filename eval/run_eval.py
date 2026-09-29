"""Evaluation harness for DevOps Copilot Agent.

Evaluates orchestrator decision accuracy and tracks false-positive rates
against fixture-based known-good and known-bad repository states.
Exits with non-zero status if false-positive rate exceeds the 10% threshold.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

# Bootstrap project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.orchestrator import DevOpsOrchestrator
from agent.tools.improvement_advisor import ImprovementProposal


def load_eval_cases(cases_dir: Path) -> List[Dict[str, Any]]:
    """Discover and parse all eval case fixtures."""
    cases = []
    for file in sorted(cases_dir.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            cases.append(data)
        except Exception as e:
            print(f"Warning: Failed to load {file}: {e}")
    return cases


def evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a single test case against orchestrator logic."""
    repo_state = case["repo_state"]
    stale_branches = case.get("stale_branches", [])
    cve_findings = case.get("cve_findings", {})
    outdated_deps = case.get("outdated_deps", [])
    ground_truth = case["ground_truth"]

    proposal = None
    if case.get("candidate_improvement"):
        proposal = ImprovementProposal(**case["candidate_improvement"])

    pre_pr_pass = case.get("pre_pr_verification_pass", True)

    orchestrator = DevOpsOrchestrator(repo=repo_state["repo"], dry_run=True)

    with patch("agent.orchestrator.verify_changes_with_tests", return_value=(pre_pr_pass, "Eval verification mock")):
        findings, summary_text = orchestrator.decide(
            repo_state,
            stale_branches,
            outdated_deps=outdated_deps,
            candidate_improvement=proposal,
            cve_findings=cve_findings,
        )

    # Determine actual action taken
    actual_action = "none"
    actual_type = "none"
    if findings:
        first_finding = findings[0]
        actual_type = first_finding.type
        if "issue" in first_finding.action_taken:
            actual_action = "issue"
        elif "pr" in first_finding.action_taken:
            actual_action = "pr"

    expected_action = ground_truth.get("expected_action", "none")
    expected_type = ground_truth.get("expected_type", "none")
    should_flag = ground_truth.get("should_flag", False)
    is_worthwhile = ground_truth.get("is_worthwhile_improvement", True)

    # Define False Positive:
    # 1. Deterministic non-issue flagged as actionable
    # 2. Improvement flagged as PR when ground truth labeled as not worthwhile/broken
    is_false_positive = False
    if not should_flag and actual_action != "none":
        is_false_positive = True
    elif actual_type == "improvement" and not is_worthwhile and actual_action == "pr":
        is_false_positive = True

    # Correctness check
    is_correct = (actual_action == expected_action) and (
        expected_action == "none" or actual_type == expected_type
    )

    return {
        "id": case["id"],
        "description": case.get("description", ""),
        "expected_action": expected_action,
        "actual_action": actual_action,
        "expected_type": expected_type,
        "actual_type": actual_type,
        "is_correct": is_correct,
        "is_false_positive": is_false_positive,
        "summary": summary_text,
    }


def run_all_evals(cases_dir: Path, max_fp_rate: float = 0.10) -> Dict[str, Any]:
    """Execute evaluation across all discovered fixture cases."""
    cases = load_eval_cases(cases_dir)
    if not cases:
        raise RuntimeError(f"No eval cases found in {cases_dir}")

    results = []
    false_positives = 0
    correct_count = 0

    for case in cases:
        res = evaluate_case(case)
        results.append(res)
        if res["is_false_positive"]:
            false_positives += 1
        if res["is_correct"]:
            correct_count += 1

    total = len(cases)
    fp_rate = false_positives / total
    accuracy = correct_count / total
    passed = fp_rate <= max_fp_rate

    return {
        "total_cases": total,
        "correct_decisions": correct_count,
        "accuracy": accuracy,
        "false_positives": false_positives,
        "false_positive_rate": fp_rate,
        "max_fp_rate_threshold": max_fp_rate,
        "passed": passed,
        "case_results": results,
    }


def main():
    cases_dir = Path(__file__).parent / "cases"
    print(f"=== Running DevOps Copilot Agent Evaluation Suite ===")
    print(f"Test cases directory: {cases_dir.resolve()}\n")

    summary = run_all_evals(cases_dir, max_fp_rate=0.10)

    print(f"{'Case ID':<35} {'Expected':<18} {'Actual':<18} {'Status'}")
    print("-" * 80)
    for r in summary["case_results"]:
        exp = f"{r['expected_action']}:{r['expected_type']}"
        act = f"{r['actual_action']}:{r['actual_type']}"
        status = "PASS" if r["is_correct"] else "FAIL"
        if r["is_false_positive"]:
            status = "FALSE_POSITIVE"
        print(f"{r['id']:<35} {exp:<18} {act:<18} {status}")

    print("-" * 80)
    print(f"Total Cases:          {summary['total_cases']}")
    print(f"Correct Decisions:    {summary['correct_decisions']}/{summary['total_cases']} ({summary['accuracy']*100:.1f}%)")
    print(f"False Positives:      {summary['false_positives']}")
    print(f"False Positive Rate:  {summary['false_positive_rate']*100:.1f}% (Threshold: <= {summary['max_fp_rate_threshold']*100:.1f}%)")
    print(f"Eval Suite Result:    {'PASSED' if summary['passed'] else 'FAILED'}")

    if not summary["passed"]:
        print(f"\n[ERROR] False positive rate exceeded allowed threshold of {summary['max_fp_rate_threshold']*100:.1f}%!")
        sys.exit(1)
    else:
        print("\n[SUCCESS] Evaluation suite passed within acceptable quality thresholds.")
        sys.exit(0)


if __name__ == "__main__":
    main()
