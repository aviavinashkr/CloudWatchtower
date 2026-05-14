# ============================================================
# demo/main.tf — Intentionally Flawed Terraform
#
# This file contains DELIBERATE security and cost issues
# so you can test the Gemini Cloud Sentinel review bot.
# Run a PR with this file and watch the bot flag the issues!
# ============================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"   # ⚠️  SENTINEL SHOULD FLAG: v4.x is available
    }
  }
}

provider "azurerm" {
  features {}
}

# ── Resource Group ───────────────────────────────────────────
resource "azurerm_resource_group" "demo" {
  name     = var.resource_group_name
  location = var.location

  # ⚠️  SENTINEL SHOULD FLAG: Missing required tags (environment, owner, cost_center)
}

# ── Virtual Network ──────────────────────────────────────────
resource "azurerm_virtual_network" "demo" {
  name                = "vnet-demo"
  address_space       = ["10.0.0.0/16"]
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
}

resource "azurerm_subnet" "demo" {
  name                 = "snet-demo"
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.demo.name
  address_prefixes     = ["10.0.1.0/24"]
}

# ── Network Security Group ───────────────────────────────────
resource "azurerm_network_security_group" "demo" {
  name                = "nsg-demo"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name

  # 🚨 CRITICAL: Open SSH to the entire internet
  security_rule {
    name                       = "AllowSSH"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "0.0.0.0/0"   # ← OPEN TO WORLD
    destination_address_prefix = "*"
  }

  # 🚨 HIGH: Open RDP to the entire internet
  security_rule {
    name                       = "AllowRDP"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3389"
    source_address_prefix      = "0.0.0.0/0"   # ← OPEN TO WORLD
    destination_address_prefix = "*"
  }

  # ⚠️  SENTINEL SHOULD FLAG: No diagnostic settings attached
}

resource "azurerm_subnet_network_security_group_association" "demo" {
  subnet_id                 = azurerm_subnet.demo.id
  network_security_group_id = azurerm_network_security_group.demo.id
}

# ── Public IP ────────────────────────────────────────────────
resource "azurerm_public_ip" "demo" {
  name                = "pip-demo"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  allocation_method   = "Static"
  sku                 = "Standard"
  # ⚠️  MEDIUM: Static public IP left exposed; consider Azure Bastion instead
}

# ── Virtual Machine ──────────────────────────────────────────
resource "azurerm_network_interface" "demo" {
  name                = "nic-demo"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name

  ip_configuration {
    name                          = "ipconfig-demo"
    subnet_id                     = azurerm_subnet.demo.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.demo.id
  }
}

resource "azurerm_linux_virtual_machine" "demo" {
  name                = "vm-demo"
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  size                = "Standard_D16s_v3"   # 💰 SENTINEL SHOULD FLAG: Way oversized

  admin_username = "adminuser"

  # 🚨 CRITICAL: Hard-coded password in Terraform!
  admin_password                  = "P@ssword1234!"   # ← NEVER DO THIS
  disable_password_authentication = false

  network_interface_ids = [azurerm_network_interface.demo.id]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    # ⚠️  MEDIUM: Should be Premium_LRS for production workloads
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "UbuntuServer"
    sku       = "18.04-LTS"    # ⚠️  SENTINEL SHOULD FLAG: EOL image, use 22.04-LTS
    version   = "latest"
  }

  # ⚠️  SENTINEL SHOULD FLAG: No auto-shutdown schedule for dev/test VM
  # ⚠️  SENTINEL SHOULD FLAG: No boot diagnostics enabled
  # ⚠️  SENTINEL SHOULD FLAG: Missing tags
}

# ── Storage Account ──────────────────────────────────────────
resource "azurerm_storage_account" "demo" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.demo.name
  location                 = azurerm_resource_group.demo.location
  account_tier             = "Standard"
  account_replication_type = "LRS"   # 💰 Consider GRS only if cross-region needed

  # 🚨 HIGH: Public blob access enabled
  allow_nested_items_to_be_public = true   # ← DANGEROUS

  # 🚨 HIGH: Minimum TLS version not enforced
  # min_tls_version = "TLS1_2"  # ← This line is MISSING
  # test 1
  # ⚠️  SENTINEL SHOULD FLAG: No network rules / private endpoint
  # ⚠️  SENTINEL SHOULD FLAG: Missing tags
}
