"""
test_github_client.py — Unit tests for the GitHub API client module.

All HTTP calls are mocked with pytest-mock and the requests library.
"""

import json
import zipfile
from io import BytesIO
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from sentinel.github_client import (
    get_pr_diff,
    post_pr_comment,
    get_workflow_logs,
    get_workflow_runs,
    get_default_branch,
    get_branch_sha,
    create_fix_branch,
    create_remediation_pr,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_response(status_code: int, body, headers: dict = None) -> MagicMock:
    """Create a mocked requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = json.dumps(body)
        resp.content = json.dumps(body).encode("utf-8")
    elif isinstance(body, bytes):
        resp.text = body.decode("utf-8", errors="replace")
        resp.json.return_value = {}
        resp.content = body
    else:
        resp.text = body
        resp.json.return_value = {}
        resp.content = body.encode("utf-8")
    if headers:
        resp.headers = headers
    return resp


def _make_log_zip(content: str = "ERROR: something went wrong") -> bytes:
    """Create a minimal ZIP archive containing a single log file."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("1_deploy/1_Terraform Apply.txt", content)
    return buf.getvalue()


# ─── Tests: get_pr_diff ─────────────────────────────────────────────────────

class TestGetPrDiff:

    @patch("sentinel.github_client.requests.get")
    def test_returns_diff_text(self, mock_get):
        diff_text = "diff --git a/main.tf b/main.tf\n+resource..."
        mock_get.return_value = _make_response(200, diff_text)

        result = get_pr_diff("owner/repo", 42, token="fake-token")
        assert result == diff_text

    @patch("sentinel.github_client.requests.get")
    def test_sends_diff_accept_header(self, mock_get):
        mock_get.return_value = _make_response(200, "diff content")
        get_pr_diff("owner/repo", 42, token="fake-token")

        call_kwargs = mock_get.call_args
        assert "application/vnd.github.diff" in call_kwargs[1]["headers"]["Accept"]

    @patch("sentinel.github_client.requests.get")
    def test_raises_on_404(self, mock_get):
        mock_get.return_value = _make_response(404, "Not Found")
        with pytest.raises(RuntimeError, match="GitHub API error"):
            get_pr_diff("owner/repo", 999, token="fake-token")

    def test_raises_without_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            get_pr_diff("owner/repo", 1, token=None)


# ─── Tests: post_pr_comment ─────────────────────────────────────────────────

class TestPostPrComment:

    @patch("sentinel.github_client.requests.post")
    def test_posts_comment_successfully(self, mock_post):
        mock_post.return_value = _make_response(
            201, {"html_url": "https://github.com/owner/repo/pull/1#comment-123"}
        )
        result = post_pr_comment("owner/repo", 1, "Analysis here", token="fake-token")
        assert result["html_url"].endswith("#comment-123")

    @patch("sentinel.github_client.requests.post")
    def test_comment_includes_sentinel_header(self, mock_post):
        mock_post.return_value = _make_response(201, {"html_url": "..."})
        post_pr_comment("owner/repo", 1, "My analysis", token="fake-token")

        posted_body = mock_post.call_args[1]["json"]["body"]
        assert "Gemini Cloud Sentinel" in posted_body
        assert "Gemini 1.5 Flash" in posted_body

    @patch("sentinel.github_client.requests.post")
    def test_raises_on_403(self, mock_post):
        mock_post.return_value = _make_response(403, "Forbidden")
        with pytest.raises(RuntimeError, match="GitHub API error"):
            post_pr_comment("owner/repo", 1, "body", token="fake-token")


# ─── Tests: get_workflow_logs ───────────────────────────────────────────────

class TestGetWorkflowLogs:

    @patch("sentinel.github_client.requests.get")
    def test_extracts_log_content(self, mock_get):
        log_content = "ERROR: AuthorizationFailed — no write permission"
        zip_bytes = _make_log_zip(log_content)
        mock_get.return_value = _make_response(200, zip_bytes)
        mock_get.return_value.content = zip_bytes

        result = get_workflow_logs("owner/repo", 12345, token="fake-token")
        assert "AuthorizationFailed" in result

    @patch("sentinel.github_client.requests.get")
    def test_truncates_very_long_logs(self, mock_get):
        long_log = "x" * 100_000
        zip_bytes = _make_log_zip(long_log)
        mock_get.return_value = _make_response(200, zip_bytes)
        mock_get.return_value.content = zip_bytes

        result = get_workflow_logs("owner/repo", 12345, token="fake-token", max_chars=50_000)
        assert len(result) <= 50_000


# ─── Tests: get_default_branch ─────────────────────────────────────────────

class TestGetDefaultBranch:

    @patch("sentinel.github_client.requests.get")
    def test_returns_main(self, mock_get):
        mock_get.return_value = _make_response(200, {"default_branch": "main"})
        result = get_default_branch("owner/repo", token="fake-token")
        assert result == "main"

    @patch("sentinel.github_client.requests.get")
    def test_returns_master(self, mock_get):
        mock_get.return_value = _make_response(200, {"default_branch": "master"})
        result = get_default_branch("owner/repo", token="fake-token")
        assert result == "master"


# ─── Tests: create_remediation_pr ──────────────────────────────────────────

class TestCreateRemediationPr:

    @patch("sentinel.github_client.requests.get")
    @patch("sentinel.github_client.requests.post")
    def test_creates_pr_with_correct_title(self, mock_post, mock_get):
        mock_get.return_value = _make_response(200, {"default_branch": "main"})
        mock_post.return_value = _make_response(
            201,
            {"html_url": "https://github.com/owner/repo/pull/99", "number": 99},
        )

        result = create_remediation_pr(
            "owner/repo",
            "sentinel/fix-run-123",
            "Root cause: missing permission",
            run_id=123,
            token="fake-token",
        )

        posted_body = mock_post.call_args[1]["json"]
        assert "123" in posted_body["title"]
        assert "sentinel" in posted_body["title"].lower()
        assert result["html_url"] == "https://github.com/owner/repo/pull/99"

    @patch("sentinel.github_client.requests.get")
    @patch("sentinel.github_client.requests.post")
    def test_pr_body_includes_analysis(self, mock_post, mock_get):
        mock_get.return_value = _make_response(200, {"default_branch": "main"})
        mock_post.return_value = _make_response(
            201, {"html_url": "...", "number": 99}
        )

        create_remediation_pr(
            "owner/repo",
            "sentinel/fix",
            "My detailed analysis here",
            run_id=456,
            token="fake-token",
        )

        pr_body = mock_post.call_args[1]["json"]["body"]
        assert "My detailed analysis here" in pr_body
        assert "Auto-Remediation" in pr_body
