<div align="center">

# 🛡️ Gemini Cloud Sentinel

### Self-Healing Infrastructure Governance Bot

*A GitHub-native AI agent that monitors Terraform Pull Requests and CI/CD pipeline failures.
Powered by **Google Gemini 1.5 Flash**.*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Gemini 1.5 Flash](https://img.shields.io/badge/Gemini-1.5%20Flash-4285F4?logo=google)](https://aistudio.google.com/)
[![Terraform](https://img.shields.io/badge/Terraform-AzureRM-7B42BC?logo=terraform)](https://registry.terraform.io/providers/hashicorp/azurerm/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

</div>

---

## 🌟 What It Does

The Gemini Cloud Sentinel is not just another linting tool — it **reasons** about your infrastructure. Instead of simple rule-matching, it leverages large language model intelligence to provide the kind of feedback a Senior DevOps Architect would give.

| Feature | Description |
|---------|-------------|
| **🔍 PR Governance Review** | Analyzes every Terraform diff with security, cost, and deprecation checks before it merges |
| **💰 Cost Optimisation** | Flags oversized VM SKUs, unnecessary public IPs, and unoptimised storage configurations |
| **🔐 Security Analysis** | Catches open NSG rules, exposed storage, hard-coded secrets, and missing encryption |
| **🛠️ Auto-Remediation** | When a pipeline fails, downloads logs, diagnoses the root cause, and opens a fix PR automatically |
| **📚 Live Documentation** | MCP server gives Gemini real-time access to the latest Terraform provider docs |
| **📋 Internal Governance** | Injects your organisation's NSG policies, tagging standards, and VM sizing rules into every analysis |

---

## 🏗️ Architecture

```
Developer PR ──▶ GitHub Actions ──▶ sentinel.py ──▶ Gemini 1.5 Flash ──▶ PR Comment
                                         │
Pipeline Fail ──▶ GitHub Actions ──▶ auto_remediate.py ──▶ Fix Branch + PR
                                         │
                                    mcp_server.py
                                    ┌────────────┐
                                    │ TF Registry│  ← Live provider docs
                                    │ Internal   │  ← Your org standards
                                    │ Wiki       │
                                    └────────────┘
```

See [docs/architecture.md](./docs/architecture.md) for the full detailed architecture.

---

## 🚀 Quick Start

### 1. Clone and install

```bash
git clone https://github.com/your-username/CloudWatchtower.git
cd CloudWatchtower
pip install -r requirements.txt
cp .env.example .env   # Fill in your keys
```

### 2. Add GitHub Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `GEMINI_API_KEY` | ✅ | From [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `SENTINEL_PAT` | ✅ | GitHub PAT with `repo` + `workflow` scopes |
| `AZURE_CLIENT_ID` | ☑️ Optional | Azure SP for environment context |
| `AZURE_CLIENT_SECRET` | ☑️ Optional | Azure SP secret |
| `AZURE_TENANT_ID` | ☑️ Optional | Azure tenant |
| `AZURE_SUBSCRIPTION_ID` | ☑️ Optional | Azure subscription |
| `MCP_SERVER_URL` | ☑️ Optional | Deployed MCP server URL |

### 3. Test locally

```bash
# Review a Terraform diff
git diff HEAD~1 -- '*.tf' | python -m sentinel.sentinel --mode review

# Analyze a failure log
python -m sentinel.sentinel --mode remediate --logs-file failure.log

# Start the MCP server
uvicorn sentinel.mcp_server:app --port 8000 --reload
```

### 4. Run tests

```bash
pytest tests/ -v
```

---

## 📁 Project Structure

```
CloudWatchtower/
├── .github/
│   └── workflows/
│       ├── sentinel-review.yml       # PR governance review
│       └── sentinel-remediate.yml    # Auto-remediation on failure
├── sentinel/
│   ├── sentinel.py                   # Core Gemini brain
│   ├── github_client.py              # GitHub API helpers
│   ├── auto_remediate.py             # Self-healing orchestrator
│   └── mcp_server.py                 # Model Context Protocol server
├── demo/
│   ├── main.tf                       # Intentionally flawed Terraform
│   ├── variables.tf
│   └── outputs.tf
├── tests/
│   ├── test_sentinel.py              # Unit tests (Gemini mocked)
│   └── test_github_client.py         # Unit tests (HTTP mocked)
├── docs/
│   ├── architecture.md               # System architecture
│   └── setup.md                      # Step-by-step setup guide
├── requirements.txt
├── .env.example
├── Dockerfile
└── pyproject.toml
```

---

## 🔬 Demo: Test the Bot

The `demo/main.tf` file contains **intentional Terraform issues** for testing:

- 🚨 **CRITICAL**: SSH port 22 open to `0.0.0.0/0` (entire internet)
- 🚨 **CRITICAL**: Hard-coded admin password in the VM resource
- 🔴 **HIGH**: RDP port 3389 open to the internet
- 🔴 **HIGH**: Storage account with public blob access enabled
- ⚠️ **MEDIUM**: Oversized VM SKU (`Standard_D16s_v3`)
- ⚠️ **MEDIUM**: Missing resource tags (environment, owner, cost_center)
- ⚠️ **MEDIUM**: Outdated Ubuntu image (`18.04-LTS` is EOL)
- ℹ️ **LOW**: AzureRM provider version pinned to outdated `~> 3.0`

Open a PR with changes to this file and watch the Sentinel report them all!

---

## 🧩 MCP Server Endpoints

The Model Context Protocol server exposes Gemini to live, up-to-date information:

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /tools` | List all available tools |
| `GET /tools/fetch_azure_tf_docs?resource_type=azurerm_nsg` | Latest AzureRM provider docs |
| `GET /tools/get_provider_versions?provider=hashicorp/azurerm` | Latest provider version |
| `GET /tools/get_internal_wiki?topic=nsg_policy` | Internal governance standards |
| `GET /tools/get_context_bundle` | Batch fetch docs + wiki in one call |

---

## 🐳 Docker

```bash
# Build
docker build -t gemini-sentinel .

# Run the MCP server
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  gemini-sentinel

# Run a diff review
docker run --rm \
  -e GEMINI_API_KEY=your_key \
  -v $(pwd)/my.diff:/diff.tf:ro \
  gemini-sentinel \
  python -m sentinel.sentinel --mode review --diff-file /diff.tf
```

---

## 📖 Full Documentation

- [Setup Guide](./docs/setup.md) — Complete step-by-step instructions
- [Architecture](./docs/architecture.md) — Detailed system design and data flows

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Write tests for your changes
4. Ensure all tests pass: `pytest tests/ -v`
5. Open a Pull Request — the Sentinel will review your Terraform changes! 🛡️

---

## 📄 License

MIT License — see [LICENSE](./LICENSE) for details.

---

<div align="center">
<i>Built with ❤️ using Google Gemini 1.5 Flash and GitHub Actions</i>
</div>