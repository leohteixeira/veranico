output "api_url" {
  description = "Address of the product (the API role, which also serves the interface)."
  value       = google_cloud_run_v2_service.api.uri
}

output "carrier_url" {
  description = "Address of the mock carrier."
  value       = google_cloud_run_v2_service.carrier.uri
}

output "registry" {
  description = "Registry path the image is pushed to, without the image name."
  value       = module.foundation.registry
}

output "federation_provider" {
  description = "Workload Identity Federation provider the deploy workflow authenticates with."
  value       = module.foundation.federation_provider
}

output "deployer" {
  description = "Account the deploy workflow acts as."
  value       = module.foundation.deployer
}
