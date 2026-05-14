# Architecture — Gemini Cloud Sentinel

## System Overview

The Gemini Cloud Sentinel is a GitHub-native AI agent that monitors Terraform
Pull Requests and GitHub Actions pipeline failures. It uses Gemini 1.5 Flash
to reason about infrastructure changes and auto-generate fixes.

---

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub Repository                            │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────────────────────────────┐  │
│  │  Developer   │    │          GitHub Actions                  │  │
│  │  Opens PR    │───▶│                                          │  │
│  │  with .tf    │    │  sentinel-review.yml                     │  │
│  │  changes     │    │  ┌────────────────────────────────────┐  │  │
│  └──────────────┘    │  │ 1. git diff HEAD~1..HEAD -- *.tf   │  │  │
│                      │  │ 2. [Optional] Fetch MCP context    │  │  │
│  ┌──────────────┐    │  │ 3. python -m sentinel.sentinel     │  │  │
│  │  Pipeline    │    │  │    --mode review                   │  │  │
│  │  Failure     │───▶│  │ 4. Post comment to PR              │  │  │
│  │  (any wf)   │    │  └────────────────────────────────────┘  │  │
│  └──────────────┘    │                                          │  │
│                      │  sentinel-remediate.yml                  │  │
│                      │  ┌────────────────────────────────────┐  │  │
│                      │  │ 1. Download failure logs            │  │  │
│                      │  │ 2. python -m sentinel.auto_remediate│  │  │
│                      │  │ 3. Create fix branch + PR           │  │  │
│                      │  └────────────────────────────────────┘  │  │
│                      └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │      sentinel/sentinel.py      │
                    │   (Core Gemini 1.5 Flash Brain)│
                    │                               │
                    │  analyze_terraform_diff()     │
                    │  analyze_failure_logs()       │
                    │  extract_hcl_fixes()          │
                    └───────────────┬───────────────┘
                                    │
              ┌─────────────────────▼────────────────────┐
              │         Google Gemini 1.5 Flash API       │
              │                                          │
              │  Model: gemini-1.5-flash                 │
              │  Temp: 0.2 (deterministic output)        │
              │  Max tokens: 8192                        │
              └──────────────────────────────────────────┘
                                    │
              ┌─────────────────────▼────────────────────┐
              │         MCP Server (FastAPI)              │
              │         sentinel/mcp_server.py            │
              │                                          │
              │  GET /tools/fetch_azure_tf_docs          │
              │  GET /tools/get_provider_versions        │
              │  GET /tools/get_internal_wiki            │
              │  GET /tools/get_context_bundle           │
              └──────────────────────────────────────────┘
                         │                   │
              ┌──────────▼──────┐  ┌─────────▼─────────┐
              │ Terraform        │  │ Internal Wiki      │
              │ Registry API     │  │ (Confluence/Notion)│
              │ (Live Docs)      │  │                   │
              └─────────────────┘  └───────────────────┘
```

---

## Data Flow: PR Review

```
1. Developer opens a PR with Terraform changes
2. sentinel-review.yml triggers on pull_request event
3. Workflow runs: git diff origin/main...HEAD -- *.tf > terraform.diff
4. [Optional] MCP server called to fetch relevant provider docs
5. sentinel.py called with --mode review --diff-file terraform.diff
6. Gemini 1.5 Flash receives: diff + MCP context + governance prompt
7. Gemini returns: security risks + cost savings + verdict (Markdown)
8. GitHub API posts the analysis as a PR comment
9. Developer sees the full governance report on their PR
```

## Data Flow: Auto-Remediation

```
1. Any GitHub Actions workflow fails (Terraform plan, apply, etc.)
2. sentinel-remediate.yml triggers on workflow_run (conclusion: failure)
3. Workflow downloads the failure logs as a ZIP archive
4. auto_remediate.py orchestrates the full remediation:
   a. Extracts and concatenates log files
   b. Calls sentinel.py --mode remediate with the logs
   c. Gemini returns: root cause + corrected HCL
   d. extract_hcl_fixes() parses out code blocks
   e. create_fix_branch() commits the corrected .tf files
   f. create_remediation_pr() opens a PR for human review
5. Team reviews the AI-generated fix and merges if correct
```

---

## Security Model

| Secret | Scope | Used By |
|--------|-------|---------|
| `GEMINI_API_KEY` | Repo secret | sentinel.py (Gemini API calls) |
| `GITHUB_TOKEN` | Built-in Actions token | Posting PR comments, reading PRs |
| `SENTINEL_PAT` | Repo secret (PAT) | Creating branches + opening PRs |
| `AZURE_CLIENT_ID` | Repo secret | MCP server Azure context (optional) |
| `AZURE_CLIENT_SECRET` | Repo secret | MCP server Azure context (optional) |
| `AZURE_TENANT_ID` | Repo secret | MCP server Azure context (optional) |
| `AZURE_SUBSCRIPTION_ID` | Repo secret | MCP server Azure context (optional) |
| `MCP_SERVER_URL` | Repo secret | Workflow MCP context fetch (optional) |

> The MCP Server, Azure secrets, and `SENTINEL_PAT` are all optional.
> The bot functions with just `GEMINI_API_KEY` and the built-in `GITHUB_TOKEN`.

---

## Prompt Engineering Strategy

### Review Prompt
- Role: "Senior DevOps Architect and Cloud Security Expert"
- Low temperature (0.2): Ensures consistent, factual output
- Structured output: Named sections for Security, Cost, Deprecation, Verdict
- Explicit severity taxonomy: CRITICAL / HIGH / MEDIUM / LOW

### Remediation Prompt
- Role: Same persona for consistency
- Log-first design: Error logs passed verbatim, never summarised
- Code-fence extraction: Fixes wrapped in ```hcl with filename comments
- Actionable output: Includes verification steps for the engineer

---

## MCP Innovation

The Model Context Protocol server is the "innovation multiplier" that gives
Gemini access to live, up-to-date information beyond its training cutoff:

1. **Live Terraform Docs**: Scrapes `registry.terraform.io` for the exact
   attributes of every resource type found in the diff. Gemini then knows
   about attributes added after its training date.

2. **Provider Version Checking**: Queries the registry API for the latest
   provider version. Gemini can flag when teams are running old provider
   versions with known bugs or removed attributes.

3. **Internal Governance Wiki**: Acts as an in-context knowledge base for
   your organisation's own standards (NSG policies, tagging requirements,
   approved VM SKUs, etc.). Gemini "reads" your rules before analysing.

4. **Context Bundling**: A single `/tools/get_context_bundle` endpoint lets
   the workflow fetch multiple doc sources in one HTTP call, keeping latency
   low in the CI/CD critical path.
