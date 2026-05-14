output "resource_group_name" {
  description = "Name of the created Resource Group"
  value       = azurerm_resource_group.demo.name
}

output "vm_private_ip" {
  description = "Private IP address of the demo VM"
  value       = azurerm_network_interface.demo.private_ip_address
}

output "vm_public_ip" {
  description = "Public IP address of the demo VM (should be removed in prod)"
  value       = azurerm_public_ip.demo.ip_address
  sensitive   = false
}

output "storage_account_name" {
  description = "Name of the Storage Account"
  value       = azurerm_storage_account.demo.name
}

output "storage_primary_endpoint" {
  description = "Primary blob endpoint"
  value       = azurerm_storage_account.demo.primary_blob_endpoint
}
