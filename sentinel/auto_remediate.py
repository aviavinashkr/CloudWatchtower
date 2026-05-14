"""
auto_remediate.py — Self-Healing Pipeline Orchestrator

When a GitHub Actions pipeline fails, this module:
  1. Downloads the failure logs from GitHub
  2. Fetches the associated Terraform diff (if available)
  3. Sends everything to Gemini 1.5 Flash for root-cause analysis
  4. Creates a fix branch with the corrected HCL
  5. Opens a Pull Request with the full analysis as the body

This script is invoked by the sentinel-remediate.yml GitHub Actions workflow.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from sentinel.sentinel import analyze_failure_logs, extract_hcl_fixes
from sentinel.github_client import (
    create_fix_branch,
    create_remediation_pr,
    get_workflow_logs,
    get_workflow_runs,
    add_pr_label,
    get_default_branch,
)

load_dotenv()
console = Console()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")


# ─── Auto-Remediation Orchestrator ─────────────────────────────────────────

def remediate(
    repo: str,
    run_id: int,
    diff: str = "",
    token: str = None,
    dry_run: bool = False,
) -> dict:
    """
    Full auto-remediation pipeline.

    Args:
        repo: Repository in 'owner/repo' format.
        run_id: The failed GitHub Actions workflow run ID.
        diff: Optional Terraform diff for additional context.
        token: GitHub PAT (falls back to GITHUB_TOKEN env var).
        dry_run: If True, print the analysis but don't create any GitHub objects.

    Returns:
        Dict with keys: 'analysis', 'hcl_fixes', 'branch_url', 'pr_url'
    """
    tok = token or os.environ.get("GITHUB_TOKEN")
    result = {
        "analysis": "",
        "hcl_fixes": [],
        "branch_url": "",
        "pr_url": "",
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:

        # ── Step 1: Download failure logs ──────────────────────────────────
        task = progress.add_task("📥 Downloading failure logs...", total=None)
        try:
            logs = get_workflow_logs(repo, run_id, token=tok)
            progress.update(task, description=f"✅ Downloaded {len(logs):,} chars of logs")
        except Exception as exc:
            console.print(f"[red]Failed to download logs:[/] {exc}")
            return result
        finally:
            progress.remove_task(task)

        # ── Step 2: Gemini analysis ────────────────────────────────────────
        task = progress.add_task("🤖 Calling Gemini 1.5 Flash...", total=None)
        try:
            analysis = analyze_failure_logs(logs, diff=diff or None)
            result["analysis"] = analysis
            progress.update(task, description="✅ Analysis complete")
        except Exception as exc:
            console.print(f"[red]Gemini analysis failed:[/] {exc}")
            return result
        finally:
            progress.remove_task(task)

    # Print the analysis
    console.print(Panel(analysis, title="🛡️ Sentinel Analysis", border_style="blue"))

    # ── Step 3: Extract HCL fixes ──────────────────────────────────────────
    hcl_fixes = extract_hcl_fixes(analysis)
    result["hcl_fixes"] = hcl_fixes

    if not hcl_fixes:
        console.print(
            "[yellow]⚠️ No corrected HCL code blocks found in the analysis. "
            "No fix branch will be created.[/]"
        )
        if dry_run:
            return result
        # Still create a PR with just the analysis (no code patches)
        branch_name = _generate_branch_name(run_id)
        _create_analysis_only_pr(repo, run_id, analysis, branch_name, tok)
        return result

    console.print(f"[green]🔧 Found {len(hcl_fixes)} HCL fix(es)[/]")
    for fix in hcl_fixes:
        console.print(f"   • [cyan]{fix['filename']}[/]")

    if dry_run:
        console.print("[yellow]DRY RUN — skipping branch and PR creation.[/]")
        return result

    # ── Step 4: Create fix branch ──────────────────────────────────────────
    branch_name = _generate_branch_name(run_id)
    file_patches = [
        {"path": fix["filename"], "content": fix["code"]}
        for fix in hcl_fixes
    ]

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"🌿 Creating fix branch '{branch_name}'...", total=None)
            branch_url = create_fix_branch(repo, branch_name, file_patches, token=tok)
            result["branch_url"] = branch_url
            progress.update(task, description=f"✅ Branch created: {branch_url}")
    except Exception as exc:
        console.print(f"[red]Failed to create fix branch:[/] {exc}")
        return result

    # ── Step 5: Open remediation PR ───────────────────────────────────────
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("📋 Opening remediation PR...", total=None)
            pr = create_remediation_pr(repo, branch_name, analysis, run_id, token=tok)
            result["pr_url"] = pr.get("html_url", "")

            # Add labels
            pr_number = pr.get("number")
            if pr_number:
                add_pr_label(
                    repo, pr_number,
                    ["sentinel-remediation", "automated", "terraform"],
                    token=tok,
                )
            progress.update(task, description=f"✅ PR opened: {result['pr_url']}")
    except Exception as exc:
        console.print(f"[red]Failed to create remediation PR:[/] {exc}")

    console.print(
        Panel(
            f"[bold green]✅ Remediation complete![/]\n\n"
            f"Branch: {result['branch_url']}\n"
            f"PR: {result['pr_url']}",
            title="🛡️ Sentinel Auto-Remediation",
            border_style="green",
        )
    )
    return result


def _generate_branch_name(run_id: int) -> str:
    """Generate a unique branch name for the remediation."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"sentinel/fix-run-{run_id}-{ts}"


def _create_analysis_only_pr(
    repo: str, run_id: int, analysis: str, branch_name: str, token: str
) -> None:
    """Create a PR with just the analysis (when no HCL fixes were extracted)."""
    try:
        pr = create_remediation_pr(repo, branch_name, analysis, run_id, token=token)
        console.print(f"[green]Analysis PR created:[/] {pr.get('html_url')}")
    except Exception as exc:
        console.print(f"[yellow]Could not create analysis PR:[/] {exc}")


# ─── CLI Entry Point ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gemini Cloud Sentinel — Auto-Remediation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-remediate a specific failed run
  python -m sentinel.auto_remediate --repo owner/repo --run-id 12345678

  # Dry run (analyze only, no GitHub changes)
  python -m sentinel.auto_remediate --repo owner/repo --run-id 12345678 --dry-run

  # Include Terraform diff for richer context
  python -m sentinel.auto_remediate --repo owner/repo --run-id 12345678 --diff-file changes.diff
        """,
    )
    parser.add_argument("--repo", required=True, help="Repository in 'owner/repo' format")
    parser.add_argument("--run-id", type=int, required=True, help="Failed workflow run ID")
    parser.add_argument("--diff-file", type=Path, help="Optional path to a Terraform diff file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only — don't create branches or PRs",
    )
    args = parser.parse_args()

    diff = ""
    if args.diff_file and args.diff_file.exists():
        diff = args.diff_file.read_text(encoding="utf-8")

    result = remediate(
        repo=args.repo,
        run_id=args.run_id,
        diff=diff,
        dry_run=args.dry_run,
    )

    if not result["analysis"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
