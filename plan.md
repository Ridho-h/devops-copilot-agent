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
- Orchestrator reads a file/module, proposes a small refactor or doc improvement
- Opens as a PR (not a direct commit), with a clear description of *why*

### Phase 5 — Browser/RPA layer
- Add Playwright-based `check_upstream_changelog` and `search_cve_advisory` tools
- Orchestrator uses these only when repo-layer info is insufficient (e.g. deciding whether a dependency bump is safe)

### Phase 6 — CVE monitoring task
- Cross-reference dependency list against advisory sources
- Opens an issue per confirmed vulnerability, with severity and suggested fix version

### Phase 7 — Eval harness
- Build a small eval set: known-good and known-bad repo states, check the orchestrator makes the right call (open issue / open PR / do nothing)
- Track false positive rate (agent flags non-issues) as the key quality metric

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
