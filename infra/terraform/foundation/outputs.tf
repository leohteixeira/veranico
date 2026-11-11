output "registry" {
  description = "Path images are pushed to and pulled from, without the image name."
  value       = "${google_artifact_registry_repository.images.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "federation_provider" {
  description = "Full name of the federation provider, the value the deploy workflow authenticates with."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer" {
  description = "Email of the account the deploy workflow acts as."
  value       = google_service_account.deployer.email
}

output "enabled_services" {
  description = "The enabled services; other resources depend on it so they are created after the services exist."
  value       = [for service in google_project_service.enabled : service.service]
}
