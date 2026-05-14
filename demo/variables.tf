variable "resource_group_name" {
  description = "Name of the Azure Resource Group"
  type        = string
  default     = "rg-sentinel-demo"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "storage_account_name" {
  description = "Globally unique storage account name (3-24 lowercase alphanumeric)"
  type        = string
  default     = "stsentineldemo001"
}
