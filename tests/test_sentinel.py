"""
test_sentinel.py — Unit tests for the Sentinel core analysis module.

All Gemini API calls are mocked to ensure tests run without credentials
and with deterministic results.
"""

import pytest
from unittest.mock import MagicMock, patch

# ─── Fixtures ──────────────────────────────────────────────────────────────

SAMPLE_DIFF = """
diff --git a/demo/main.tf b/demo/main.tf
index abc123..def456 100644
--- a/demo/main.tf
+++ b/demo/main.tf
@@ -1,10 +1,30 @@
+resource "azurerm_network_security_group" "bad" {
+  name                = "nsg-bad"
+  location            = "East US"
+  resource_group_name = "rg-demo"
+
+  security_rule {
+    name                       = "AllowSSH"
+    priority                   = 100
+    direction                  = "Inbound"
+    access                     = "Allow"
+    protocol                   = "Tcp"
+    source_port_range          = "*"
+    destination_port_range     = "22"
+    source_address_prefix      = "0.0.0.0/0"
+    destination_address_prefix = "*"
+  }
+}
"""

SAMPLE_LOGS = """
Error: creating Virtual Machine "vm-demo" (Resource Group "rg-demo"): 
compute.VirtualMachinesClient#CreateOrUpdate: Failure sending request: 
StatusCode=403 -- Original Error: Code="AuthorizationFailed" 
Message="The client 'sp-gemini-sentinel' with object id 'xxx' does not have authorization 
to perform action 'Microsoft.Compute/virtualMachines/write' over scope 
'/subscriptions/sub-id/resourceGroups/rg-demo' or the scope is invalid. 
If access was recently granted, please refresh your credentials."
"""

SAMPLE_ANALYSIS = """
## Security Analysis

### CRITICAL: Open SSH Port

**Resource**: azurerm_network_security_group.bad
**Severity**: CRITICAL
**Issue**: Port 22 is open to 0.0.0.0/0 (entire internet)

**Fix**:
```hcl
# demo/main.tf
resource "azurerm_network_security_group" "bad" {
  name                = "nsg-bad"
  location            = "East US"
  resource_group_name = "rg-demo"

  security_rule {
    name                       = "AllowSSH"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "10.0.0.0/8"
    destination_address_prefix = "*"
  }
}
```

## ✅ Verdict: CHANGES REQUESTED
"""

SAMPLE_REMEDIATION_ANALYSIS = """
## Root Cause Analysis

The deployment failed because the Service Principal lacks the 
`Microsoft.Compute/virtualMachines/write` permission.

## Fix

Add the `Contributor` role to the Service Principal:

```hcl
# demo/main.tf
resource "azurerm_role_assignment" "sp_contributor" {
  scope                = data.azurerm_subscription.current.id
  role_definition_name = "Contributor"
  principal_id         = var.service_principal_object_id
}
```
"""

MOCK_GEMINI_RESPONSE = MagicMock()
MOCK_GEMINI_RESPONSE.text = SAMPLE_ANALYSIS


# ─── Tests: analyze_terraform_diff ─────────────────────────────────────────

class TestAnalyzeTerraformDiff:

    @patch("sentinel.sentinel._get_model")
    def test_returns_analysis_string(self, mock_get_model):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MOCK_GEMINI_RESPONSE
        mock_get_model.return_value = mock_client

        from sentinel.sentinel import analyze_terraform_diff
        result = analyze_terraform_diff(SAMPLE_DIFF)

        assert isinstance(result, str)
        assert len(result) > 0

    @patch("sentinel.sentinel._get_model")
    def test_calls_gemini_once(self, mock_get_model):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MOCK_GEMINI_RESPONSE
        mock_get_model.return_value = mock_client

        from sentinel.sentinel import analyze_terraform_diff
        analyze_terraform_diff(SAMPLE_DIFF)

        mock_client.models.generate_content.assert_called_once()

    @patch("sentinel.sentinel._get_model")
    def test_diff_included_in_prompt(self, mock_get_model):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MOCK_GEMINI_RESPONSE
        mock_get_model.return_value = mock_client

        from sentinel.sentinel import analyze_terraform_diff
        analyze_terraform_diff(SAMPLE_DIFF)

        call_kwargs = mock_client.models.generate_content.call_args[1]
        prompt = call_kwargs["contents"]
        assert "0.0.0.0/0" in prompt  # Key content from diff in prompt

    def test_empty_diff_returns_warning(self):
        from sentinel.sentinel import analyze_terraform_diff
        result = analyze_terraform_diff("")
        assert "No Terraform changes" in result

    def test_whitespace_diff_returns_warning(self):
        from sentinel.sentinel import analyze_terraform_diff
        result = analyze_terraform_diff("   \n  \t  ")
        assert "No Terraform changes" in result

    @patch("sentinel.sentinel._get_model")
    def test_mcp_context_appended_to_prompt(self, mock_get_model):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MOCK_GEMINI_RESPONSE
        mock_get_model.return_value = mock_client

        from sentinel.sentinel import analyze_terraform_diff
        analyze_terraform_diff(SAMPLE_DIFF, mcp_context="NSG policy: no 0.0.0.0/0")

        call_kwargs = mock_client.models.generate_content.call_args[1]
        prompt = call_kwargs["contents"]
        assert "NSG policy: no 0.0.0.0/0" in prompt

    def test_missing_api_key_raises_environment_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from sentinel.sentinel import analyze_terraform_diff
        with pytest.raises(EnvironmentError, match="GEMINI_API_KEY"):
            analyze_terraform_diff(SAMPLE_DIFF)


# ─── Tests: analyze_failure_logs ───────────────────────────────────────────

class TestAnalyzeFailureLogs:

    @patch("sentinel.sentinel._get_model")
    def test_returns_analysis_string(self, mock_get_model):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = SAMPLE_REMEDIATION_ANALYSIS
        mock_client.models.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_client

        from sentinel.sentinel import analyze_failure_logs
        result = analyze_failure_logs(SAMPLE_LOGS)

        assert isinstance(result, str)
        assert len(result) > 0

    @patch("sentinel.sentinel._get_model")
    def test_logs_included_in_prompt(self, mock_get_model):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = SAMPLE_REMEDIATION_ANALYSIS
        mock_client.models.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_client

        from sentinel.sentinel import analyze_failure_logs
        analyze_failure_logs(SAMPLE_LOGS)

        call_kwargs = mock_client.models.generate_content.call_args[1]
        prompt = call_kwargs["contents"]
        assert "AuthorizationFailed" in prompt

    @patch("sentinel.sentinel._get_model")
    def test_diff_included_when_provided(self, mock_get_model):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = SAMPLE_REMEDIATION_ANALYSIS
        mock_client.models.generate_content.return_value = mock_response
        mock_get_model.return_value = mock_client

        from sentinel.sentinel import analyze_failure_logs
        analyze_failure_logs(SAMPLE_LOGS, diff=SAMPLE_DIFF)

        call_kwargs = mock_client.models.generate_content.call_args[1]
        prompt = call_kwargs["contents"]
        assert "0.0.0.0/0" in prompt  # From diff

    def test_empty_logs_returns_warning(self):
        from sentinel.sentinel import analyze_failure_logs
        result = analyze_failure_logs("")
        assert "No failure logs" in result


# ─── Tests: extract_hcl_fixes ──────────────────────────────────────────────

class TestExtractHclFixes:

    def test_extracts_single_fix(self):
        from sentinel.sentinel import extract_hcl_fixes
        fixes = extract_hcl_fixes(SAMPLE_ANALYSIS)
        assert len(fixes) == 1
        assert fixes[0]["filename"] == "demo/main.tf"
        assert "azurerm_network_security_group" in fixes[0]["code"]

    def test_extracts_multiple_fixes(self):
        multi_fix_analysis = """
```hcl
# main.tf
resource "azurerm_resource_group" "rg" {
  name = "rg-test"
}
```

```hcl
# variables.tf
variable "location" {
  default = "East US"
}
```
"""
        from sentinel.sentinel import extract_hcl_fixes
        fixes = extract_hcl_fixes(multi_fix_analysis)
        assert len(fixes) == 2
        assert fixes[0]["filename"] == "main.tf"
        assert fixes[1]["filename"] == "variables.tf"

    def test_empty_analysis_returns_empty_list(self):
        from sentinel.sentinel import extract_hcl_fixes
        fixes = extract_hcl_fixes("")
        assert fixes == []

    def test_analysis_without_hcl_returns_empty_list(self):
        from sentinel.sentinel import extract_hcl_fixes
        fixes = extract_hcl_fixes("No code here, just text.")
        assert fixes == []

    def test_default_filename_when_no_comment(self):
        from sentinel.sentinel import extract_hcl_fixes
        analysis = "```hcl\nresource \"azurerm_rg\" \"x\" {}\n```"
        fixes = extract_hcl_fixes(analysis)
        assert len(fixes) == 1
        assert fixes[0]["filename"] == "fix.tf"
