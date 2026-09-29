# DevOps Copilot Agent

An autonomous, scheduled LLM-orchestrated agent that keeps personal GitHub repositories healthy without waiting for issues or PRs to appear. It runs on a schedule, inspects the current repository state, decides what needs attention, and takes the smallest safe action — filing an issue or opening a verified pull request for human review.

## Architecture & Priority Hierarchy

The agent evaluates repository findings according to a strict priority hierarchy:

1. **`ci_failure` (Top Priority)**: Detects failing GitHub Actions workflow runs on default/main branches. Cites run ID, workflow name, URL, and conclusion.
2. **`cve_advisory` (Security Risk)**: Queries OSV.dev and security registries for vulnerabilities affecting dependencies. Filters for `MEDIUM` severity or above, deduplicates multiple CVEs into a single issue per package, and recommends fixed versions.
3. **`stale_branches` (Hygiene)**: Detects branches with no commit activity for 30+ days that have not been merged into the default branch.
4. **`outdated_dependencies` (Maintenance)**: Checks PyPI and npm registries for packages pinned behind latest releases. Formats a clear markdown table with current vs latest versions.
   - *Overlap Rule*: If a package has both an outdated version and a CVE advisory, the separate outdated issue is suppressed to avoid alert duplication.
5. **`improvement` (Targeted Proposals)**:
   - *Narrow Scope Allow-List*: Restricts suggestions strictly to `docstrings`, `readme_gaps`, `type_hints`, and `dead_code` (no open-ended refactors).
   - *Frequency Capping*: At most 1 improvement proposal per 14 days, checked directly against live GitHub PR history.
   - *Pre-PR Verification*: Temporarily applies changes and runs the repository test suite (`pytest`). Only opens a PR if all tests pass.
   - *Low-Confidence Fallback*: If tests fail or confidence is low, the agent **never** opens a PR — it falls back to opening an issue for human review.
6. **`none` (Quiet Run)**: If no issues meet the action threshold, logs "no action needed this run." A quiet run is a correct and expected outcome.

---

## Repository Structure

```text
devops-copilot-agent/
├── .github/
│   └── workflows/
│       ├── scheduled-run.yml    # Weekly cron orchestrator run
│       └── pr-eval.yml          # Pull request CI quality gate
├── agent/
│   ├── orchestrator.py          # Core orchestrator and decision loop
│   ├── prompts/
│   │   ├── orchestrator_prompt.md  # Orchestrator system prompt
│   │   └── RULES.md                # Orchestration guidelines
│   ├── tools/
│   │   ├── github_tools.py      # GitHub REST client & API tools
│   │   ├── browser_tools.py     # Playwright/HTTP changelog & CVE lookups
│   │   ├── dependency_checker.py# PyPI/npm version checking
│   │   ├── cve_scanner.py       # Vulnerability scanner & dedup engine
│   │   ├── improvement_advisor.py# Allow-list & pre-PR test runner
│   │   └── verify_github_tools.py # CLI live verification script
│   └── requirements.txt         # Runtime and test dependencies
├── eval/
│   ├── cases/                   # 11 fixture-based evaluation cases
│   └── run_eval.py              # Eval runner & false-positive rate calculator
├── tests/                       # Comprehensive pytest suite (52 tests)
└── pyproject.toml               # Pytest configuration
```

---

## Getting Started

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/<your-username>/devops-copilot-agent.git
cd devops-copilot-agent

# Install dependencies
pip install -r agent/requirements.txt

# (Optional) Install Playwright browser dependencies for full browser RPA
python -m playwright install --with-deps chromium
```

### 2. Configuration (`.env`)

Create a `.env` file in the project root:

```env
GITHUB_TOKEN=ghp_yourPersonalAccessTokenHere
GITHUB_REPOSITORY=owner/repo-name
GEMINI_API_KEY=your_gemini_api_key_here
```

Required GitHub token permissions:
- `contents: write` (to create branches and commit changes for PRs)
- `issues: write` (to open issues)
- `pull-requests: write` (to open pull requests)

---

## Running the Agent

### Dry-Run Mode (Safe Local Testing)

Run the orchestrator locally against any public repository without creating real issues or PRs:

```bash
python agent/orchestrator.py octocat/Hello-World --dry-run
```

Output:
```text
Run Date: 2026-09-27T02:56:30+00:00
Repo:     octocat/Hello-World
Summary:  [DRY RUN] Would open issue: Stale branches detected (>30 days inactive)
Findings: 1
  - [stale_branches] Action: dry_run_issue | Ref: dry_run://octocat/Hello-World/issues/...
    Evidence: [DRY RUN] Would open issue for 2 stale branch(es)
```

### Live Run

```bash
python agent/orchestrator.py your-org/your-repo
```

A structured run log is automatically recorded to `agent/run_log.json` on each cycle for auditing and telemetry.

---

## Testing & Quality Gates

### Unit Test Suite

Run the full automated test suite:

```bash
pytest
```

52 automated tests cover:
- GitHub API client, rate limiting, and PR safety checks
- PyPI/npm dependency version parsing and comparisons
- Upstream changelog analysis and breaking change heuristics
- OSV.dev CVE advisory lookup and severity filtering
- Pre-PR test verification and file rollback guarantees
- Decision loop prioritization and duplicate issue suppression

### Eval Quality Gate (<10% False Positive Rate)

Run the fixture-based evaluation harness:

```bash
python eval/run_eval.py
```

Evaluates 11 realistic test cases (known-good repos, failing CI, high/low CVEs, stale branches, outdated dependencies, and proposed improvements). Exits with code `1` if the false-positive rate exceeds **10.0%**.

The eval suite runs automatically on every pull request via [`.github/workflows/pr-eval.yml`](.github/workflows/pr-eval.yml).

---

## Scheduled GitHub Actions Deployment

The agent is pre-configured with [`.github/workflows/scheduled-run.yml`](.github/workflows/scheduled-run.yml) to execute weekly on Mondays at 09:00 UTC (or manually via `workflow_dispatch`).

1. Enable GitHub Actions in your repository.
2. In **Settings > Secrets and variables > Actions**, configure:
   - `GITHUB_TOKEN`: Standard repository token with `contents: write`, `issues: write`, `pull-requests: write`.
   - `GEMINI_API_KEY`: API key for Google Gemini model reasoning.
3. Each run outputs run logs and uploads `agent/run_log.json` as an Actions artifact preserved for 30 days.
