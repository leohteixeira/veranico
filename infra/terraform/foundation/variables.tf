variable "project_id" {
  description = "Google Cloud project that holds every resource."
  type        = string
}

variable "region" {
  description = "Region of the registry."
  type        = string
}

variable "billing_account" {
  description = "Billing account whose budget the deployer manages."
  type        = string
}

variable "github_repository" {
  description = "The only repository whose workflows may deploy, as owner/name."
  type        = string
}

variable "github_repository_id" {
  description = "Numeric identifier of that repository; when set, the federation also requires it."
  type        = string
  default     = null
}
