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
You are a **Senior DevOps Architect and Cloud Security Expert** specialising in
Terraform, Azure, and Infrastructure-as-Code best practices.

You have been given a Terraform git diff from a Pull Request. Your job is to
produce a structured governance report.

---

## TERRAFORM DIFF
```hcl
{diff}
```

---

## YOUR TASKS

### 1. 🔐 Security Analysis
Identify every security risk in the diff. For each risk, provide:
- **Severity**: CRITICAL | HIGH | MEDIUM | LOW
- **Resource**: the Terraform resource name
- **Issue**: clear description of the problem
- **Fix**: the corrected HCL snippet

Look specifically for:
- Open Network Security Group rules (0.0.0.0/0 ingress)
- Publicly exposed storage accounts or blobs
- Missing encryption (at-rest and in-transit)
- Hard-coded credentials or secrets
- Overly permissive IAM/RBAC roles
- Missing diagnostic settings / audit logging
- Disabled TLS or weak TLS versions

### 2. 💰 Cost Optimisation
Identify cost-saving opportunities. For each:
- **Resource**: Terraform resource name
- **Issue**: what is over-provisioned or wasteful
- **Recommendation**: the right-sized or cheaper alternative
- **Estimated saving**: rough monthly saving (if estimable)

Look specifically for:
- Oversized VM SKUs (e.g., Standard_D16s_v3 when Standard_B2s suffices)
- Non-reserved compute instances for stable workloads
- LRS vs GRS storage where durability needs are low
- Public IP addresses left attached to stopped resources
- Missing auto-shutdown schedules for dev/test VMs

### 3. 🔄 Deprecation & Compatibility Warnings
- Flag any deprecated Terraform attributes or old provider versions
- Suggest the modern equivalent syntax

### 4. ✅ Summary & Verdict
Provide an overall assessment:
- **APPROVED** — safe to merge with no or only low-severity findings
- **APPROVED WITH WARNINGS** — merge allowed but address medium-severity items
- **CHANGES REQUESTED** — high/critical findings must be fixed before merge

Format your entire response as clean Markdown so it renders well as a GitHub PR comment.
"""

FAILURE_PROMPT_TEMPLATE = """
You are a **Senior DevOps Architect and Cloud Security Expert** specialising in
Terraform, Azure, and CI/CD pipelines.

A GitHub Actions pipeline has failed. Your job is to diagnose the root cause
and generate a corrected fix.

---

## PIPELINE FAILURE LOGS
```
{logs}
```

{diff_section}

---

## YOUR TASKS

### 1. 🔍 Root Cause Analysis
Explain in plain English exactly why this deployment failed.
Be specific — reference exact error messages from the logs.

### 2. 🛠️ Step-by-Step Fix
Provide numbered steps the engineer must take to resolve this.

### 3. 📝 Corrected HCL Code
If the failure is caused by incorrect Terraform code, provide the full
corrected HCL snippet. Wrap it in a fenced code block tagged `hcl`.
Also provide the corrected file name as a comment at the top of the block.

### 4. 🔄 Required GitHub Secrets / Azure Permissions
List any missing environment variables, GitHub Secrets, or Azure RBAC
permissions that need to be added.

### 5. ✅ Verification Steps
How can the engineer verify the fix worked after re-running the pipeline?

Format your entire response as clean Markdown so it renders well as a GitHub PR comment.
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
