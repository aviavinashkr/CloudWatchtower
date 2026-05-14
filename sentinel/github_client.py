"""
github_client.py — GitHub API Helpers for Gemini Cloud Sentinel

Handles all GitHub interactions: fetching diffs, posting PR comments,
downloading workflow logs, creating fix branches, and opening PRs.
"""

import base64
import logging
import os
import time
import zipfile
from io import BytesIO
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


# ─── Auth ──────────────────────────────────────────────────────────────────

def _headers(token: Optional[str] = None) -> dict:
    tok = token or os.environ.get("GITHUB_TOKEN")
    if not tok:
        raise EnvironmentError(
            "GITHUB_TOKEN environment variable is not set. "
            "Create a PAT at https://github.com/settings/tokens "
            "(required scopes: repo, workflow)"
        )
    return {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _raise_for_status(response: requests.Response, context: str) -> None:
    if not response.ok:
        raise RuntimeError(
            f"GitHub API error during '{context}': "
            f"{response.status_code} — {response.text[:500]}"
        )


# ─── PR Helpers ────────────────────────────────────────────────────────────

def get_pr_diff(repo: str, pr_number: int, token: Optional[str] = None) -> str:
    """
    Fetch the unified diff for a Pull Request.

    Args:
        repo: Repository in 'owner/repo' format.
        pr_number: The PR number.
        token: GitHub PAT (falls back to GITHUB_TOKEN env var).

    Returns:
        Raw unified diff as a string.
    """
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    headers = _headers(token)
    headers["Accept"] = "application/vnd.github.diff"

    logger.info("Fetching diff for PR #%d in %s", pr_number, repo)
    resp = requests.get(url, headers=headers, timeout=30)
    _raise_for_status(resp, f"get_pr_diff PR#{pr_number}")
    return resp.text


def post_pr_comment(
    repo: str,
    pr_number: int,
    body: str,
    token: Optional[str] = None,
) -> dict:
    """
    Post a comment on a Pull Request.

    Args:
        repo: Repository in 'owner/repo' format.
        pr_number: The PR number.
        body: The comment body (Markdown supported).
        token: GitHub PAT (falls back to GITHUB_TOKEN env var).

    Returns:
        The created comment object from the API.
    """
    # Add a sentinel header to the comment for easy identification
    header = (
        "## 🛡️ Gemini Cloud Sentinel Report\n\n"
        "> *Automated analysis powered by Gemini 1.5 Flash*\n\n"
        "---\n\n"
    )
    full_body = header + body

    url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    logger.info("Posting sentinel comment to PR #%d in %s", pr_number, repo)
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"body": full_body},
        timeout=30,
    )
    _raise_for_status(resp, f"post_pr_comment PR#{pr_number}")
    result = resp.json()
    logger.info("Comment posted: %s", result.get("html_url"))
    return result


def get_open_prs(repo: str, token: Optional[str] = None) -> list[dict]:
    """Return a list of open PRs for the repository."""
    url = f"{GITHUB_API}/repos/{repo}/pulls?state=open&per_page=100"
    resp = requests.get(url, headers=_headers(token), timeout=30)
    _raise_for_status(resp, "get_open_prs")
    return resp.json()


# ─── Workflow / Log Helpers ────────────────────────────────────────────────

def get_workflow_runs(
    repo: str,
    status: str = "failure",
    token: Optional[str] = None,
) -> list[dict]:
    """
    Return recent workflow runs with the given status.

    Args:
        repo: Repository in 'owner/repo' format.
        status: Filter by status — 'failure', 'success', etc.
        token: GitHub PAT.

    Returns:
        List of workflow run objects.
    """
    url = f"{GITHUB_API}/repos/{repo}/actions/runs?status={status}&per_page=10"
    resp = requests.get(url, headers=_headers(token), timeout=30)
    _raise_for_status(resp, "get_workflow_runs")
    return resp.json().get("workflow_runs", [])


def get_workflow_logs(
    repo: str,
    run_id: int,
    token: Optional[str] = None,
    max_chars: int = 50_000,
) -> str:
    """
    Download and return the logs for a workflow run.

    GitHub returns logs as a ZIP archive; we extract and concatenate all
    log files, then truncate to `max_chars` to stay within model limits.

    Args:
        repo: Repository in 'owner/repo' format.
        run_id: The workflow run ID.
        token: GitHub PAT.
        max_chars: Maximum characters to return (default 50k).

    Returns:
        Concatenated log text.
    """
    url = f"{GITHUB_API}/repos/{repo}/actions/runs/{run_id}/logs"
    logger.info("Downloading logs for run %d in %s", run_id, repo)
    resp = requests.get(
        url,
        headers=_headers(token),
        timeout=60,
        allow_redirects=True,
    )
    _raise_for_status(resp, f"get_workflow_logs run#{run_id}")

    logs_text = ""
    with zipfile.ZipFile(BytesIO(resp.content)) as zf:
        for name in sorted(zf.namelist()):
            with zf.open(name) as f:
                chunk = f.read().decode("utf-8", errors="replace")
                logs_text += f"\n\n=== {name} ===\n{chunk}"

    if len(logs_text) > max_chars:
        logger.warning(
            "Logs truncated from %d to %d chars", len(logs_text), max_chars
        )
        logs_text = logs_text[-max_chars:]  # Keep the END (most relevant errors)

    return logs_text.strip()


# ─── Branch & PR Helpers ───────────────────────────────────────────────────

def get_default_branch(repo: str, token: Optional[str] = None) -> str:
    """Return the default branch name (usually 'main' or 'master')."""
    url = f"{GITHUB_API}/repos/{repo}"
    resp = requests.get(url, headers=_headers(token), timeout=30)
    _raise_for_status(resp, "get_default_branch")
    return resp.json()["default_branch"]


def get_branch_sha(repo: str, branch: str, token: Optional[str] = None) -> str:
    """Return the latest commit SHA for a branch."""
    url = f"{GITHUB_API}/repos/{repo}/git/ref/heads/{branch}"
    resp = requests.get(url, headers=_headers(token), timeout=30)
    _raise_for_status(resp, f"get_branch_sha {branch}")
    return resp.json()["object"]["sha"]


def create_fix_branch(
    repo: str,
    branch_name: str,
    file_patches: list[dict],
    base_branch: Optional[str] = None,
    token: Optional[str] = None,
) -> str:
    """
    Create a new branch with patched Terraform files.

    Args:
        repo: Repository in 'owner/repo' format.
        branch_name: Name for the new fix branch.
        file_patches: List of dicts with keys:
                      - 'path': file path in the repo (str)
                      - 'content': new file content (str)
        base_branch: Branch to base off (default: repo's default branch).
        token: GitHub PAT.

    Returns:
        The URL of the newly created branch.
    """
    hdrs = _headers(token)
    base = base_branch or get_default_branch(repo, token)
    base_sha = get_branch_sha(repo, base, token)

    # 1. Create the new branch ref
    ref_url = f"{GITHUB_API}/repos/{repo}/git/refs"
    resp = requests.post(
        ref_url,
        headers=hdrs,
        json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        timeout=30,
    )
    _raise_for_status(resp, f"create_branch {branch_name}")
    logger.info("Created branch: %s", branch_name)

    # 2. Commit each patched file
    for patch in file_patches:
        file_path = patch["path"]
        content = patch["content"]
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

        # Check if file exists (to get its SHA for updates)
        file_url = f"{GITHUB_API}/repos/{repo}/contents/{file_path}?ref={branch_name}"
        check_resp = requests.get(file_url, headers=hdrs, timeout=30)
        existing_sha = check_resp.json().get("sha") if check_resp.ok else None

        payload = {
            "message": f"fix(sentinel): auto-remediate {file_path}",
            "content": encoded,
            "branch": branch_name,
        }
        if existing_sha:
            payload["sha"] = existing_sha

        commit_resp = requests.put(file_url, headers=hdrs, json=payload, timeout=30)
        _raise_for_status(commit_resp, f"commit_file {file_path}")
        logger.info("Committed fix: %s", file_path)

    branch_url = f"https://github.com/{repo}/tree/{branch_name}"
    return branch_url


def create_remediation_pr(
    repo: str,
    branch_name: str,
    analysis: str,
    run_id: int,
    base_branch: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    """
    Open a Pull Request with the Gemini-generated remediation.

    Args:
        repo: Repository in 'owner/repo' format.
        branch_name: The fix branch to open a PR from.
        analysis: The full Gemini analysis (used as PR body).
        run_id: The failed workflow run ID (for cross-referencing).
        base_branch: Target branch for the PR.
        token: GitHub PAT.

    Returns:
        The created PR object from the API.
    """
    base = base_branch or get_default_branch(repo, token)

    body = (
        "## 🛡️ Gemini Cloud Sentinel — Auto-Remediation PR\n\n"
        f"> This PR was **automatically generated** by Gemini Cloud Sentinel "
        f"in response to a failed workflow run (Run ID: `{run_id}`).\n\n"
        "---\n\n"
        f"{analysis}\n\n"
        "---\n\n"
        "_Please review the changes carefully before merging. "
        "Auto-generated fixes should always be validated by a human engineer._"
    )

    url = f"{GITHUB_API}/repos/{repo}/pulls"
    resp = requests.post(
        url,
        headers=_headers(token),
        json={
            "title": f"fix: 🛡️ Sentinel auto-remediation for run #{run_id}",
            "body": body,
            "head": branch_name,
            "base": base,
            "draft": False,
        },
        timeout=30,
    )
    _raise_for_status(resp, "create_remediation_pr")
    result = resp.json()
    logger.info("Remediation PR created: %s", result.get("html_url"))
    return result


def add_pr_label(
    repo: str,
    pr_number: int,
    labels: list[str],
    token: Optional[str] = None,
) -> None:
    """Add labels to a PR, creating them if they don't exist."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/labels"
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"labels": labels},
        timeout=30,
    )
    if not resp.ok:
        logger.warning("Could not add labels to PR #%d: %s", pr_number, resp.text[:200])
