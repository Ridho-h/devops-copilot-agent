# DevOps Copilot Agent — Implementation Plan

## Overview
An LLM-orchestrated agent that keeps personal GitHub repos healthy without waiting for issues/PRs to show up. It runs on a schedule, decides what needs attention, and either fixes small things directly or opens an issue/PR for review. It combines a repo-automation layer (GitHub API, CI checks) with a browser/RPA layer (Playwright) so it isn't limited to information already inside the repo.

## Scope (MVP)
In scope for v1:
- Scheduled health checks (deps, CI status, stale branches)
- Self-generated improvement suggestions (opened as PRs)
- Dependency / CVE monitoring (opened as issues)

Out of scope for v1 (planned for v2):
- Changelog/README auto-maintenance
- Cross-repo consistency enforcement

## Architecture recap
1. **Trigger** — scheduled GitHub Actions workflow (cron), one run per repo per cycle.
2. **Orchestrator** — single LLM agent. Reads repo state, decides which task(s) apply this run, calls tools, writes output. Kept as one agent for v1 to avoid coordination overhead.
3. **Repo automation layer** — GitHub API / MCP GitHub server: read commits, issues, PRs, CI status; open issues/PRs; never pushes directly to main.
4. **Browser/RPA layer** — Playwright (or MCP browser tool): check upstream changelogs, search for CVE advisories, verify a fix exists before suggesting it.
5. **Output** — GitHub issues or PRs only. No autonomous commits to main — human review stays in the loop.

## Build phases

### Phase 1 — Repo layer foundation
- Set up GitHub API/MCP access (read repo metadata, issues, PRs, commit history)
- Implement `open_issue`, `open_pr`, `get_ci_status`, `list_dependencies` tool functions
- Manual test: run against one real repo, confirm read access and a test issue can be opened

### Phase 2 — Orchestrator core
- Write the orchestrator system prompt (see `orchestrator_prompt.md`)
- Wire orchestrator to Phase 1 tools only (no browser yet)
- Orchestrator can decide "nothing to do" vs "run task X" — this decision loop is the core of the project

### Phase 3 — Health check task
- Implement: stale branch detection, failing CI detection, outdated dependency detection
- Orchestrator opens one issue per distinct finding (not a bundled summary), reusing the duplicate-suppression logic from Phase 2 to avoid re-filing the same problem on every run

### Phase 4 — Improvement suggestion task
- Scope guardrail: restrict suggestions to a narrow allow-list (docstrings, README gaps, missing type hints, obvious dead code) — no open-ended refactors. Cap frequency to at most one improvement suggestion per repo per N runs, not every run.
- Orchestrator reads a file/module, proposes one change within the allow-list, with a clear description of *why*
- Pre-PR verification: generate the change, run the repo's own test suite against it locally (skip this check only if the repo has no test suite), and only open the PR if tests still pass
- Low-confidence fallback: if the orchestrator isn't confident the change is correct or safe (including when the pre-PR test run fails), open an issue describing the suggestion instead of a PR — do not fall back to opening a PR anyway
- Opens as a PR (not a direct commit) only when the above checks pass

### Phase 5 — Browser/RPA layer
- Add Playwright-based `check_upstream_changelog` and `search_cve_advisory` tools
- Orchestrator uses these only when repo-layer info is insufficient (e.g. deciding whether a dependency bump is safe)

### Phase 6 — CVE monitoring task
- Cross-reference dependency list against advisory sources
- Priority order update: `cve_advisory` findings rank right after `ci_failure` and ahead of `stale_branches`, `outdated_dependencies`, and `improvement` — a known vulnerability is a security risk, not routine maintenance. Full order: `ci_failure` → `cve_advisory` → `stale_branches` → `outdated_dependencies` → `improvement` → `none`
- Overlap with `outdated_dependencies`: if a package has both a pending version bump and a known CVE, skip the separate "outdated" issue for that package and file only the CVE issue (it's more urgent and implies an update anyway) — never file both for the same package in one run
- Severity filtering: only file an issue for `medium` severity or above; dedupe multiple CVEs affecting the same package into a single issue listing all of them, rather than one issue per CVE
- Opens an issue per confirmed vulnerability (post-filtering/dedupe), with severity and suggested fix version

### Phase 7 — Eval harness
- Build a small eval set: known-good and known-bad repo states, check the orchestrator makes the right call (open issue / open PR / do nothing)
- Fixture-based, not live repos: eval cases use recorded/synthetic GitHub API and registry responses (mocked, like the existing unit tests), not live calls to real repos — deterministic and repeatable on every run, no API cost
- Per-finding-type definition of a false positive:
  - `ci_failure`, `cve_advisory`, `outdated_dependencies` — deterministic; a false positive here is a tool-function bug (wrong parsing/comparison), tested with fixed input/output fixture pairs
  - `improvement` — judgment-based; a false positive is proposing something trivial or unhelpful even when tests pass. Requires a hand-reviewed case set (human-labeled "worth suggesting" vs "not worth it"), not just assert-equal checks
- Concrete threshold: false positive rate must stay under 10% across the eval set to pass; `run_eval.py` exits non-zero if exceeded
- CI integration: add a step (or a second lightweight workflow) that runs `eval/run_eval.py` on every PR touching `agent/`, so future orchestrator changes can't silently regress the false-positive rate

### Phase 8 — Deployment
- GitHub Actions workflow per repo, scheduled weekly
- Secrets: GitHub token (scoped, least-privilege), any API keys for CVE sources
- Logging: keep a run log (what was checked, what was decided, what was opened) for auditability

## Tech stack
- Python (agent logic, tool functions)
- MCP for tool orchestration (GitHub tool + browser tool)
- Playwright for browser/RPA
- GitHub Actions for scheduling
- Simple eval harness (consistent with prior projects) for Phase 7

## Suggested repo structure
```
devops-copilot-agent/
  agent/
    orchestrator.py
    prompts/
      orchestrator_prompt.md
    tools/
      github_tools.py
      browser_tools.py
  eval/
    cases/
    run_eval.py
  .github/workflows/
    scheduled-run.yml
  README.md
```

## Success metrics for v1
- Runs unattended on a schedule without errors
- Opens at least one useful issue/PR per repo over a multi-week test period
- False positive rate on the eval set stays low (agent doesn't spam low-value issues)
