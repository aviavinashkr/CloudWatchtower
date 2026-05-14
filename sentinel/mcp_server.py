"""
mcp_server.py — Model Context Protocol Server for Gemini Cloud Sentinel

A lightweight FastAPI server that exposes "tools" to Gemini via function calling.
This allows Gemini to fetch real-time, up-to-date context rather than relying
solely on its training data.

Available tools:
  - fetch_azure_tf_docs: Get the latest AzureRM Terraform provider documentation
  - get_provider_versions: Check the latest Terraform provider version on the registry
  - get_internal_wiki: Retrieve internal wiki/runbook entries
  - get_azure_resource_info: Query live Azure resource details (with SP auth)

Usage:
  uvicorn sentinel.mcp_server:app --host 0.0.0.0 --port 8000
"""

import logging
import os
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gemini Cloud Sentinel — MCP Server",
    description=(
        "Model Context Protocol server that gives Gemini 1.5 Flash "
        "real-time access to Terraform documentation, provider versions, "
        "and internal runbooks."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ─── Internal Wiki ─────────────────────────────────────────────────────────
# In production, replace this with a call to your Confluence/Notion/SharePoint API.

INTERNAL_WIKI: dict[str, str] = {
    "nsg_policy": """
# NSG Policy — Internal Standard

All Azure Network Security Groups (NSGs) MUST comply with the following:

1. **No 0.0.0.0/0 ingress rules** — Use specific IP ranges or Azure Service Tags.
2. **Port 22 (SSH) and 3389 (RDP)** must ONLY be accessible from the corporate VPN
   IP range: `10.0.0.0/8` or via Azure Bastion.
3. **All NSGs must have diagnostic settings** pointing to the central Log Analytics
   workspace: `/subscriptions/xxx/resourceGroups/rg-monitoring/providers/...`
4. **Priority range 100-199** is reserved for platform-managed rules.

Reference: Azure Security Benchmark v3 — NS-1, NS-2
""",
    "tagging_policy": """
# Azure Resource Tagging Policy — Internal Standard

All Azure resources provisioned via Terraform MUST include these tags:

| Tag Key        | Description                         | Example              |
|----------------|-------------------------------------|----------------------|
| environment    | Deployment environment              | dev / staging / prod |
| project        | Project or workload name            | gemini-sentinel      |
| owner          | Team or individual responsible      | devops@company.com   |
| cost_center    | Finance cost center code            | CC-1234              |
| managed_by     | Provisioning method                 | terraform            |

Missing tags will cause policy compliance failures and chargeback issues.
""",
    "vm_sizing": """
# VM SKU Guidance — Cost Optimisation Standard

## Recommended SKUs by Workload

| Workload Type       | Recommended SKU        | Avoid                    |
|---------------------|------------------------|--------------------------|
| Dev/Test (single)   | Standard_B2s           | D-series, E-series       |
| Web frontend        | Standard_B4ms          | Any Lsv2 or M-series     |
| CI/CD runners       | Standard_D4s_v5        | GPU series               |
| Database (prod)     | Standard_E8s_v5        | Legacy v2 or v3          |
| AI/ML workloads     | Standard_NC4as_T4_v3   | Standard_NC6 (legacy)    |

## Auto-Shutdown Policy
All dev/test VMs MUST have an auto-shutdown schedule set to 19:00 UTC.
Use the `azurerm_dev_test_global_vm_shutdown_schedule` resource.
""",
    "tf_provider_guidance": """
# Terraform Provider Version Guidance

## AzureRM Provider
- **Minimum required version**: `>= 3.100.0`
- **Recommended pinned version**: `~> 4.0`
- **Breaking changes in v4**: The `azurerm_virtual_network` block no longer
  supports inline `subnet` blocks. Use separate `azurerm_subnet` resources.
- **v3 deprecated attributes** (will error in v4):
  - `azurerm_storage_account.account_encryption_source` → use `identity` block
  - `azurerm_kubernetes_cluster.addon_profile` → use top-level blocks

## AzureAD → AzureRM/AzAPI Migration
The `azuread` provider is being superseded by native support in `azapi`.
For new identity resources, prefer the `azapi` provider.
""",
}


# ─── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "gemini-cloud-sentinel-mcp"}


@app.get("/tools")
def list_tools() -> dict:
    """List all available MCP tools."""
    return {
        "tools": [
            {
                "name": "fetch_azure_tf_docs",
                "description": "Fetch official Terraform AzureRM provider documentation for a resource type",
                "parameters": {"resource_type": "string (e.g. azurerm_network_security_group)"},
                "endpoint": "/tools/fetch_azure_tf_docs",
            },
            {
                "name": "get_provider_versions",
                "description": "Get the latest version of a Terraform provider from the registry",
                "parameters": {"provider": "string (e.g. hashicorp/azurerm)"},
                "endpoint": "/tools/get_provider_versions",
            },
            {
                "name": "get_internal_wiki",
                "description": "Retrieve internal wiki/runbook entries for governance topics",
                "parameters": {"topic": "string (nsg_policy | tagging_policy | vm_sizing | tf_provider_guidance)"},
                "endpoint": "/tools/get_internal_wiki",
            },
        ]
    }


@app.get("/tools/fetch_azure_tf_docs")
async def fetch_azure_tf_docs(
    resource_type: str = Query(..., description="e.g. azurerm_network_security_group"),
) -> JSONResponse:
    """
    Fetch the official Terraform AzureRM documentation for a given resource type.

    Scrapes the Terraform registry and returns the argument reference section,
    giving Gemini accurate, up-to-date attribute information.
    """
    resource_type = resource_type.strip().lower()
    if not re.match(r"^azurerm_[a-z0-9_]+$", resource_type):
        raise HTTPException(status_code=400, detail="Invalid resource_type format.")

    url = f"https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/{resource_type[8:]}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "GeminiCloudSentinel/1.0"})
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Documentation not found for '{resource_type}'. URL: {url}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Terraform registry: {exc}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract the main documentation content
    content_div = soup.find("div", {"class": re.compile(r"docs|content|markdown", re.I)})
    if not content_div:
        content_div = soup.find("main") or soup.find("article") or soup.body

    text = content_div.get_text(separator="\n", strip=True) if content_div else resp.text[:5000]

    # Trim to a reasonable length
    if len(text) > 8000:
        text = text[:8000] + "\n\n[...truncated — see full docs at: " + url + "]"

    return JSONResponse({
        "resource_type": resource_type,
        "source_url": url,
        "documentation": text,
    })


@app.get("/tools/get_provider_versions")
async def get_provider_versions(
    provider: str = Query("hashicorp/azurerm", description="e.g. hashicorp/azurerm"),
) -> JSONResponse:
    """
    Query the Terraform registry for the latest provider version and changelog.
    """
    provider = provider.strip().lower()
    if not re.match(r"^[a-z0-9_-]+/[a-z0-9_-]+$", provider):
        raise HTTPException(status_code=400, detail="Invalid provider format. Use 'namespace/name'.")

    namespace, name = provider.split("/", 1)
    api_url = f"https://registry.terraform.io/v1/providers/{namespace}/{name}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(api_url, headers={"User-Agent": "GeminiCloudSentinel/1.0"})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Terraform registry: {exc}")

    return JSONResponse({
        "provider": provider,
        "latest_version": data.get("version", "unknown"),
        "published_at": data.get("published_at", "unknown"),
        "source": data.get("source", ""),
        "description": data.get("description", ""),
        "registry_url": f"https://registry.terraform.io/providers/{provider}/latest",
    })


@app.get("/tools/get_internal_wiki")
def get_internal_wiki(
    topic: str = Query(..., description="Wiki topic key"),
) -> JSONResponse:
    """
    Retrieve an internal governance wiki entry.

    Supported topics: nsg_policy, tagging_policy, vm_sizing, tf_provider_guidance
    """
    topic = topic.strip().lower()
    if topic not in INTERNAL_WIKI:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Topic '{topic}' not found. "
                f"Available topics: {', '.join(INTERNAL_WIKI.keys())}"
            ),
        )
    return JSONResponse({
        "topic": topic,
        "content": INTERNAL_WIKI[topic].strip(),
        "note": "This is internal governance documentation. Treat as authoritative.",
    })


@app.get("/tools/get_context_bundle")
async def get_context_bundle(
    resource_types: str = Query("", description="Comma-separated list of azurerm_ resource types"),
    wiki_topics: str = Query("", description="Comma-separated list of wiki topics"),
) -> JSONResponse:
    """
    Fetch multiple docs in one call — optimised for Gemini function calling.
    Returns a single bundled context string ready to inject into a Gemini prompt.
    """
    bundle = []

    for rt in [r.strip() for r in resource_types.split(",") if r.strip()]:
        try:
            doc_resp = await fetch_azure_tf_docs(resource_type=rt)
            doc_data = doc_resp.body
            import json
            doc_json = json.loads(doc_data)
            bundle.append(
                f"## Terraform Docs: {rt}\n\n{doc_json.get('documentation', '')}\n"
            )
        except HTTPException as exc:
            bundle.append(f"## {rt}: [Doc fetch failed — {exc.detail}]\n")

    for topic in [t.strip() for t in wiki_topics.split(",") if t.strip()]:
        if topic in INTERNAL_WIKI:
            bundle.append(f"## Internal Wiki: {topic}\n\n{INTERNAL_WIKI[topic].strip()}\n")

    return JSONResponse({
        "context": "\n---\n".join(bundle),
        "sources": resource_types.split(",") + wiki_topics.split(","),
    })


# ─── Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_SERVER_PORT", "8000"))
    uvicorn.run("sentinel.mcp_server:app", host=host, port=port, reload=True)
