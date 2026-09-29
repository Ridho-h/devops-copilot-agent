import pytest
from pathlib import Path
from eval.run_eval import load_eval_cases, evaluate_case, run_all_evals


def test_load_eval_cases():
    cases_dir = Path("eval/cases")
    cases = load_eval_cases(cases_dir)
    assert len(cases) >= 10
    ids = [c["id"] for c in cases]
    assert "case_01_clean_healthy" in ids
    assert "case_02_ci_failure" in ids
    assert "case_03_high_cve" in ids
    assert "case_07_cve_outdated_overlap" in ids


def test_evaluate_clean_case():
    cases_dir = Path("eval/cases")
    cases = {c["id"]: c for c in load_eval_cases(cases_dir)}
    clean_case = cases["case_01_clean_healthy"]

    result = evaluate_case(clean_case)
    assert result["is_correct"] is True
    assert result["is_false_positive"] is False
    assert result["actual_action"] == "none"


def test_evaluate_cve_outdated_overlap_case():
    cases_dir = Path("eval/cases")
    cases = {c["id"]: c for c in load_eval_cases(cases_dir)}
    overlap_case = cases["case_07_cve_outdated_overlap"]

    result = evaluate_case(overlap_case)
    assert result["is_correct"] is True
    assert result["is_false_positive"] is False
    assert result["actual_type"] == "cve_advisory"


def test_run_all_evals_passes_threshold():
    cases_dir = Path("eval/cases")
    results = run_all_evals(cases_dir)

    assert results["total_cases"] >= 10
    assert results["false_positive_rate"] <= 0.10
    assert results["accuracy"] >= 0.90
    assert results["passed"] is True
