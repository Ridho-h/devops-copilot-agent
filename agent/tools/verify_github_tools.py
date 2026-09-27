"""Manual verification script for GitHub automation tools."""

import argparse
import json
import os
import sys
from dotenv import load_dotenv

from agent.tools.github_tools import (
    get_repo_state,
    open_issue,
    get_stale_branches,
    get_rate_limit,
)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Verify GitHub tools against a real repository.")
    parser.add_argument("--repo", type=str, help="Repository in 'owner/repo' format (or env GITHUB_REPO)")
    parser.add_argument("--create-test-issue", action="store_true", help="Create a test issue to verify write access")
    args = parser.parse_args()

    repo = args.repo or os.environ.get("GITHUB_REPO")
    token = os.environ.get("GITHUB_TOKEN")

    if not repo:
        print("Error: Specify repository via --repo owner/repo or GITHUB_REPO env var.")
        sys.exit(1)

    print(f"--- Verifying GitHub API Read Access for {repo} ---")
    if not token:
        print("Note: GITHUB_TOKEN not set. Running unauthenticated (public repos only, rate-limited to 60 req/hr).")
    else:
        print("GITHUB_TOKEN detected.")

    try:
        limits = get_rate_limit(token)
        core = limits.get("core", {})
        print(f"Rate Limit: {core.get('remaining')}/{core.get('limit')} remaining (resets at {core.get('reset')})")
    except Exception as e:
        print(f"Could not check rate limit: {e}")

    try:
        state = get_repo_state(repo, token=token)
        print("\nRepo Metadata:")
        print(f"  Default Branch: {state.get('default_branch')}")
        print(f"  Description:    {state.get('description')}")
        print(f"  Recent Commits: {len(state.get('recent_commits', []))} fetched")
        print(f"  Open Issues:    {len(state.get('open_issues', []))} found")
        print(f"  Open PRs:       {len(state.get('open_prs', []))} found")
        print(f"  CI Status:      {state.get('ci_status', {}).get('status')}")
        print(f"  Dependencies:   {len(state.get('dependencies', {}))} found")
        if state.get("dependencies"):
            print("  Sample deps:", list(state.get("dependencies").items())[:5])

        stale = get_stale_branches(repo, days_threshold=30, token=token)
        print(f"  Stale Branches: {len(stale)} branches >30d inactive")

        print("\n[SUCCESS] Read access verified successfully!")

    except Exception as e:
        print(f"\n[FAIL] Read access failed: {e}")
        sys.exit(1)

    if args.create_test_issue:
        if not token:
            print("\n[SKIP] Cannot create test issue without GITHUB_TOKEN.")
            return

        print(f"\n--- Testing Write Access (Creating Issue in {repo}) ---")
        try:
            issue = open_issue(
                repo=repo,
                title="[DevOps Copilot] Test Issue — Verification",
                body="This is an automated verification issue created during Phase 1 testing of DevOps Copilot Agent.",
                labels=["devops-copilot"],
                token=token,
            )
            print(f"[SUCCESS] Issue #{issue.get('number')} created: {issue.get('html_url')}")
        except Exception as e:
            print(f"[FAIL] Write access failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
