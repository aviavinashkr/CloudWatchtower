# Setup Guide — Gemini Cloud Sentinel

This guide walks you through a complete setup from zero to a working,
AI-powered Terraform governance bot in your GitHub repository.

---

## Prerequisites

- Python 3.11+
- Git
- A GitHub account with a repository containing Terraform files
- (Optional) An Azure subscription with rights to create Service Principals

---

## Step 1 — Get a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click **"Create API key"**
3. Copy the key — you'll add it as a GitHub Secret in Step 4

> **Model used**: `gemini-1.5-flash` — chosen for its speed and low latency
> in CI/CD environments where response time directly affects pipeline duration.

---

## Step 2 — Create a GitHub Personal Access Token (PAT)

The built-in `GITHUB_TOKEN` can post comments but **cannot create branches**
or **open PRs that trigger further workflows**. You need a PAT for the
auto-remediation workflow.

1. Go to [GitHub Settings → Tokens](https://github.com/settings/tokens)
2. Click **"Generate new token (classic)"**
3. Give it a descriptive name: `sentinel-bot`
4. Select these scopes:
   - ✅ `repo` (full repository access)
   - ✅ `workflow` (read/write Actions workflows)
5. Set expiration to your preference
6. Click **"Generate token"** and copy the value

---

## Step 3 — Azure Service Principal (Optional)

The Azure SP is optional but enables richer analysis. Gemini can cross-reference
your live Azure environment with the proposed Terraform changes.

```bash
# Login to Azure
az login

# Create a Service Principal with Reader access
az ad sp create-for-rbac \
  --name "gemini-sentinel" \
  --role "Reader" \
  --scopes "/subscriptions/<YOUR_SUBSCRIPTION_ID>" \
  --output json
```

This outputs:
```json
{
  "appId": "<AZURE_CLIENT_ID>",
  "displayName": "gemini-sentinel",
  "password": "<AZURE_CLIENT_SECRET>",
  "tenant": "<AZURE_TENANT_ID>"
}
```

---

## Step 4 — Configure GitHub Secrets

Go to your repository → **Settings** → **Secrets and variables** → **Actions**
→ **New repository secret** and add the following:

### Required Secrets

| Secret Name | Value | Where to get it |
|-------------|-------|-----------------|
| `GEMINI_API_KEY` | Your Gemini API key | Google AI Studio (Step 1) |
| `SENTINEL_PAT` | Your GitHub PAT | GitHub Settings (Step 2) |

### Optional Secrets (Azure Context)

| Secret Name | Value |
|-------------|-------|
| `AZURE_CLIENT_ID` | From Step 3 `appId` |
| `AZURE_CLIENT_SECRET` | From Step 3 `password` |
| `AZURE_TENANT_ID` | From Step 3 `tenant` |
| `AZURE_SUBSCRIPTION_ID` | Your Azure Subscription ID |
| `MCP_SERVER_URL` | URL where your MCP server is deployed (e.g. `https://your-server.azurewebsites.net`) |

> **Note**: The `GITHUB_TOKEN` secret is automatically provided by GitHub Actions
> — you do NOT need to create it manually.

---

## Step 5 — Local Development Setup

```bash
# Clone the repository
git clone https://github.com/your-username/CloudWatchtower.git
cd CloudWatchtower

# Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env and fill in your values
```

---

## Step 6 — Test Locally

### Test the PR Review (diff analysis):

```bash
# Generate a sample diff from the demo files
git diff HEAD -- demo/ > /tmp/test.diff

# Or create a quick test diff inline:
cat > /tmp/test.diff << 'EOF'
diff --git a/demo/main.tf b/demo/main.tf
--- a/demo/main.tf
+++ b/demo/main.tf
@@ -1,5 +1,15 @@
+resource "azurerm_network_security_group" "bad" {
+  security_rule {
+    source_address_prefix = "0.0.0.0/0"
+    destination_port_range = "22"
+  }
+}
EOF

# Run the sentinel
python -m sentinel.sentinel --mode review --diff-file /tmp/test.diff
```

### Test the Failure Analysis:

```bash
cat > /tmp/test_logs.txt << 'EOF'
Error: creating Virtual Machine "vm-demo":
Code="AuthorizationFailed"
Message="The client does not have authorization to perform action
'Microsoft.Compute/virtualMachines/write'"
EOF

python -m sentinel.sentinel --mode remediate --logs-file /tmp/test_logs.txt
```

### Start the MCP Server:

```bash
uvicorn sentinel.mcp_server:app --host 0.0.0.0 --port 8000 --reload

# In another terminal, test it:
curl http://localhost:8000/health
curl "http://localhost:8000/tools/get_internal_wiki?topic=nsg_policy"
curl "http://localhost:8000/tools/get_provider_versions?provider=hashicorp/azurerm"
```

---

## Step 7 — Run the Tests

```bash
pytest tests/ -v
```

Expected output:
```
tests/test_sentinel.py::TestAnalyzeTerraformDiff::test_returns_analysis_string PASSED
tests/test_sentinel.py::TestAnalyzeTerraformDiff::test_calls_gemini_once PASSED
tests/test_sentinel.py::TestAnalyzeTerraformDiff::test_diff_included_in_prompt PASSED
...
tests/test_github_client.py::TestGetPrDiff::test_returns_diff_text PASSED
...
```

---

## Step 8 — Test End-to-End

1. Create a new branch: `git checkout -b test/sentinel-demo`
2. Make a small change to `demo/main.tf` (e.g., change the VM size)
3. Push the branch: `git push origin test/sentinel-demo`
4. Open a Pull Request on GitHub
5. Watch the **"🛡️ Sentinel — Terraform PR Review"** workflow run
6. Check the PR for a comment from the Sentinel bot

---

## Step 9 — Deploy the MCP Server (Optional)

For the MCP server to be reachable from GitHub Actions, it needs to be
deployed to a public URL. Options:

### Option A — Azure Container Apps (Recommended)

```bash
# Build the Docker image
docker build -t gemini-sentinel .

# Push to Azure Container Registry
az acr create --resource-group rg-sentinel --name acrsentinel --sku Basic
az acr login --name acrsentinel
docker tag gemini-sentinel acrsentinel.azurecr.io/gemini-sentinel:latest
docker push acrsentinel.azurecr.io/gemini-sentinel:latest

# Deploy to Azure Container Apps
az containerapp create \
  --name gemini-sentinel-mcp \
  --resource-group rg-sentinel \
  --image acrsentinel.azurecr.io/gemini-sentinel:latest \
  --target-port 8000 \
  --ingress external \
  --env-vars GEMINI_API_KEY=secretref:gemini-api-key
```

### Option B — GitHub Codespaces / ngrok (Quick Demo)

```bash
# Start the server locally
uvicorn sentinel.mcp_server:app --port 8000

# In another terminal, expose with ngrok
ngrok http 8000
# Copy the ngrok URL and set it as MCP_SERVER_URL GitHub Secret
```

---

## Upgrading to a GitHub App (Production)

For production deployments, replace the PAT with a GitHub App for:
- Fine-grained permissions
- No personal account dependency
- Higher API rate limits

1. Go to [GitHub Developer Settings](https://github.com/settings/apps) → **New GitHub App**
2. Set the permissions: `Contents: Write`, `Pull requests: Write`, `Actions: Read`
3. Generate a private key and install on your repository
4. Use [actions/create-github-app-token](https://github.com/actions/create-github-app-token)
   in your workflows to generate short-lived tokens

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `GEMINI_API_KEY environment variable is not set` | Add the key to your `.env` file or GitHub Secrets |
| `GitHub API error: 403` | Check your PAT has the `repo` and `workflow` scopes |
| `GitHub API error: 422 (Unprocessable Entity)` | Branch may already exist; the bot uses timestamps to avoid this |
| `No corrected HCL code blocks found` | Gemini analysis ran but found no code to fix; the analysis PR is still created |
| MCP server `503` | Terraform registry is temporarily unreachable; the workflow `continue-on-error: true` means the review still runs |
