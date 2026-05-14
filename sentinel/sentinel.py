"""
sentinel.py — The Core Brain of Gemini Cloud Sentinel

Analyzes Terraform diffs and CI/CD failure logs using Gemini 2.0 Flash-Lite.
Provides actionable security, cost, and remediation insights.
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Optional

import google.genai as genai
from google.genai import types as genai_types
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# ─── Setup ─────────────────────────────────────────────────────────────────
load_dotenv()
console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
logger = logging.getLogger(__name__)


# ─── Prompts ───────────────────────────────────────────────────────────────

REVIEW_PROMPT_TEMPLATE = """
You are a Senior DevOps Architect reviewing a Terraform Pull Request.
Analyze the diff below and produce a concise governance report in Markdown.

## TERRAFORM DIFF
```hcl
{diff}
```

## TASKS

### 1. 🔐 Security Risks
For each issue: **Severity** (CRITICAL/HIGH/MEDIUM/LOW) | **Resource** | **Issue** | corrected HCL snippet.
Check for: open NSG rules (0.0.0.0/0), public storage, missing encryption, hard-coded secrets, weak TLS.

### 2. 💰 Cost Optimisation
For each: **Resource** | **Issue** | **Recommendation** | estimated saving.
Check for: oversized VM SKUs, missing auto-shutdown on dev VMs, unnecessary public IPs.

### 3. 🔄 Deprecation Warnings
Flag deprecated attributes or old provider versions with the modern alternative.

### 4. ✅ Verdict
**APPROVED** | **APPROVED WITH WARNINGS** | **CHANGES REQUESTED**
"""

FAILURE_PROMPT_TEMPLATE = """
You are a Senior DevOps Architect diagnosing a GitHub Actions pipeline failure.

## FAILURE LOGS
```
{logs}
```

{diff_section}

## TASKS

### 1. 🔍 Root Cause
Explain in plain English why this failed, referencing exact error messages.

### 2. 🛠️ Fix Steps
Numbered steps to resolve the issue.

### 3. 📝 Corrected HCL
If Terraform code caused the failure, provide the corrected snippet in a
```hcl\n# filename.tf\n``` code block.

### 4. 🔑 Missing Secrets / Permissions
List any missing GitHub Secrets or Azure RBAC permissions.

### 5. ✅ Verification
How to confirm the fix worked.
"""

DIFF_SECTION_TEMPLATE = """
## TERRAFORM DIFF (context)
```hcl
{diff}
```
"""


# ─── Gemini Client ─────────────────────────────────────────────────────────

def _get_model():
    """Configure and return a Gemini 2.0 Flash-Lite client."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is not set. "
            "Get your key at: https://aistudio.google.com/app/apikey"
        )
    client = genai.Client(api_key=api_key)
    return client


# ─── Public API ────────────────────────────────────────────────────────────

def analyze_terraform_diff(diff: str, mcp_context: Optional[str] = None) -> str:
    """
    Analyze a Terraform git diff using Gemini 2.0 Flash-Lite.

    Args:
        diff: The raw git diff output containing HCL changes.
        mcp_context: Optional additional context from the MCP server
                     (e.g., latest provider docs, internal wiki entries).

    Returns:
        A Markdown-formatted governance report.
    """
    if not diff or not diff.strip():
        return "⚠️ No Terraform changes detected in this diff."

    logger.info("Analyzing Terraform diff (%d chars)...", len(diff))

    prompt = REVIEW_PROMPT_TEMPLATE.format(diff=diff.strip())
    if mcp_context:
        prompt += f"\n\n---\n\n## ADDITIONAL CONTEXT (from MCP Server)\n{mcp_context}"

    client = _get_model()
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.2,
            top_p=0.95,
            max_output_tokens=8192,
        ),
    )
    return response.text


def analyze_failure_logs(
    logs: str,
    diff: Optional[str] = None,
    mcp_context: Optional[str] = None,
) -> str:
    """
    Analyze pipeline failure logs and generate a remediation plan.

    Args:
        logs: Raw GitHub Actions log output from the failed run.
        diff: Optional Terraform diff for additional context.
        mcp_context: Optional additional context from the MCP server.

    Returns:
        A Markdown-formatted root-cause analysis and fix.
    """
    if not logs or not logs.strip():
        return "⚠️ No failure logs provided."

    logger.info("Analyzing failure logs (%d chars)...", len(logs))

    diff_section = ""
    if diff and diff.strip():
        diff_section = DIFF_SECTION_TEMPLATE.format(diff=diff.strip())

    prompt = FAILURE_PROMPT_TEMPLATE.format(
        logs=logs.strip(),
        diff_section=diff_section,
    )
    if mcp_context:
        prompt += f"\n\n---\n\n## ADDITIONAL CONTEXT (from MCP Server)\n{mcp_context}"

    client = _get_model()
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.2,
            top_p=0.95,
            max_output_tokens=8192,
        ),
    )
    return response.text


def extract_hcl_fixes(analysis: str) -> list[dict]:
    """
    Parse Gemini's analysis response and extract corrected HCL code blocks.

    Returns:
        List of dicts with keys: 'filename' (str), 'code' (str)
    """
    fixes = []
    lines = analysis.split("\n")
    in_block = False
    current_block = []
    current_file = "fix.tf"

    for line in lines:
        if line.strip().startswith("```hcl"):
            in_block = True
            current_block = []
            # Look for a filename comment on the same line e.g. ```hcl # main.tf
            parts = line.strip().split("#")
            if len(parts) > 1:
                current_file = parts[1].strip()
            continue

        if in_block and line.strip() == "```":
            if current_block:
                fixes.append({
                    "filename": current_file,
                    "code": "\n".join(current_block),
                })
            in_block = False
            current_block = []
            current_file = "fix.tf"
            continue

        if in_block:
            # Capture inline filename comment at top of block
            if line.strip().startswith("# ") and not current_block:
                potential_file = line.strip()[2:].strip()
                if potential_file.endswith(".tf"):
                    current_file = potential_file
            current_block.append(line)

    return fixes


# ─── CLI Entry Point ────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gemini Cloud Sentinel — AI-powered Terraform governance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review a Terraform PR diff from stdin
  git diff HEAD~1 | python -m sentinel.sentinel --mode review

  # Analyze a failure log file
  python -m sentinel.sentinel --mode remediate --logs-file failure.log

  # Review with a diff file
  python -m sentinel.sentinel --mode review --diff-file changes.diff
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["review", "remediate"],
        required=True,
        help="'review' for PR diff analysis, 'remediate' for failure log analysis",
    )
    parser.add_argument(
        "--diff-file",
        type=Path,
        help="Path to a file containing the git diff (default: read from stdin)",
    )
    parser.add_argument(
        "--logs-file",
        type=Path,
        help="Path to a file containing pipeline failure logs",
    )
    parser.add_argument(
        "--output",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Write output to this file instead of stdout",
    )
    parser.add_argument(
        "--mcp-context-file",
        type=Path,
        help="Path to additional context fetched from the MCP server",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Read inputs
    diff = ""
    if args.diff_file:
        diff = args.diff_file.read_text(encoding="utf-8")
    elif not sys.stdin.isatty() and args.mode == "review":
        diff = sys.stdin.read()

    logs = ""
    if args.logs_file:
        logs = args.logs_file.read_text(encoding="utf-8")

    mcp_context = ""
    if args.mcp_context_file:
        mcp_context = args.mcp_context_file.read_text(encoding="utf-8")

    # Run analysis
    try:
        if args.mode == "review":
            if not diff:
                console.print("[red]Error:[/] No diff provided. Use --diff-file or pipe via stdin.")
                sys.exit(1)
            console.print(Panel("🔍 Analyzing Terraform diff...", style="bold blue"))
            result = analyze_terraform_diff(diff, mcp_context=mcp_context or None)

        else:  # remediate
            if not logs:
                console.print("[red]Error:[/] No logs provided. Use --logs-file.")
                sys.exit(1)
            console.print(Panel("🛠️ Analyzing pipeline failure...", style="bold yellow"))
            result = analyze_failure_logs(logs, diff=diff or None, mcp_context=mcp_context or None)

    except EnvironmentError as exc:
        console.print(f"[red]Configuration Error:[/] {exc}")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Unexpected Error:[/] {exc}")
        logger.exception("Sentinel analysis failed")
        sys.exit(1)

    # Output
    if args.output == "json":
        output_data = {
            "mode": args.mode,
            "analysis": result,
            "hcl_fixes": extract_hcl_fixes(result) if args.mode == "remediate" else [],
        }
        output_str = json.dumps(output_data, indent=2)
    else:
        output_str = result

    if args.output_file:
        args.output_file.write_text(output_str, encoding="utf-8")
        console.print(f"[green]✅ Output written to:[/] {args.output_file}")
    else:
        if args.output == "markdown":
            console.print(Markdown(output_str))
        else:
            console.print(output_str)


if __name__ == "__main__":
    main()
