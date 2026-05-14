# ============================================================
# demo/main.tf — Minimal Flawed Terraform (for Sentinel testing)
#
# Contains 3 deliberate issues for the bot to catch:
#   1. CRITICAL  — NSG with SSH open to 0.0.0.0/0
#   2. MEDIUM    — Oversized VM SKU (cost issue)
#   3. HIGH      — Storage account with public blob access
# ============================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0" # ⚠️ outdated — v4.x is available
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "demo" {
  name     = var.resource_group_name
  location = var.location
  # ⚠️ Missing tags: environment, owner, cost_center
}

# 🚨 CRITICAL: SSH open to entire internet
resource "azurerm_network_security_group" "demo" {
  name                = "nsg-demo"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name

  security_rule {
    name                       = "AllowSSH"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "0.0.0.0/0" # ← open to world
    destination_address_prefix = "*"
  }
}

# 💰 MEDIUM: Oversized VM for a dev workload
resource "azurerm_linux_virtual_machine" "demo" {
  name                            = "vm-demo"
  resource_group_name             = azurerm_resource_group.demo.name
  location                        = azurerm_resource_group.demo.location
  size                            = "Standard_D16s_v3" # ← way too large for dev
  admin_username                  = "adminuser"
  admin_password                  = "P@ssword1234!" # 🚨 hard-coded secret
  disable_password_authentication = false

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "UbuntuServer"
    sku       = "18.04-LTS" # ⚠️ EOL image
    version   = "latest"
  }
}

# 🔴 HIGH: Storage with public blob access enabled
resource "azurerm_storage_account" "demo" {
  name                            = var.storage_account_name
  resource_group_name             = azurerm_resource_group.demo.name
  location                        = azurerm_resource_group.demo.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  allow_nested_items_to_be_public = true # ← dangerous
  # ⚠️ min_tls_version not set (defaults to TLS1_0)
}
