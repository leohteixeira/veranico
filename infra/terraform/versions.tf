# Versions, the provider and the state backend.
#
# Pins (checked on 2026-11-11): Terraform 1.15.2 is the version of the development container;
# hashicorp/google 8.11.0 was the newest release on the registry. The lock file fixes the
# exact provider build.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.11"
    }
  }

  # Partial configuration: the state bucket is named at init, so no project detail is
  # written here.
  #
  #   terraform init -backend-config="bucket=<state bucket>"
  #
  # Validation and the tests need no state and no credentials:
  #
  #   terraform init -backend=false
  backend "gcs" {
    prefix = "veranico"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # The Cloud Billing Budget API bills and checks quota against a project named by the
  # caller, not against the resource; without these two settings the budget cannot be
  # managed with user credentials (provider documentation of google_billing_budget).
  billing_project       = var.project_id
  user_project_override = true
}
