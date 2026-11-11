# The two Cloud Run services: one image, two roles (SPEC 17).

module "foundation" {
  source = "./foundation"

  project_id        = var.project_id
  region            = var.region
  billing_account   = var.billing_account
  github_repository = var.github_repository

  github_repository_id = var.github_repository_id
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  image = "${module.foundation.registry}/veranico:${var.image_tag}"

  api_service     = "veranico-api"
  carrier_service = "veranico-carrier"

  # The deterministic address Cloud Run gives every service:
  # https://SERVICE-PROJECT_NUMBER.REGION.run.app (Cloud Run documentation, "HTTPS
  # requests"). It is known before the service exists, which matters twice: the API service
  # must be told its own address (Cloud Tasks calls it back there, and the address is the
  # audience of the identity tokens it accepts), and a resource cannot refer to its own
  # computed attributes.
  api_url     = "https://${local.api_service}-${data.google_project.this.number}.${var.region}.run.app"
  carrier_url = "https://${local.carrier_service}-${data.google_project.this.number}.${var.region}.run.app"

  # Port of the image (Dockerfile): Cloud Run sends requests to the container port set here.
  container_port = 8080

  api_env = merge(
    {
      APP_ROLE                        = "api"
      VERANICO_ENVIRONMENT            = "production"
      VERANICO_FIRESTORE_PROJECT      = var.project_id
      VERANICO_STORAGE_BUCKET         = google_storage_bucket.data.name
      VERANICO_BLOB_BACKEND           = "gcs"
      VERANICO_CLIMATE__STORE_BACKEND = "gcs"
      VERANICO_FRAME_ANCESTORS        = jsonencode(var.frame_ancestors)
      VERANICO_TELEMETRY__EXPORTER    = "cloud_trace"

      # Webhook delivery through Cloud Tasks. The attempt limit, the retry window and the
      # dispatch deadline are the same variables the queue is built from (async.tf).
      VERANICO_DELIVERY__DISPATCHER                      = "cloud_tasks"
      VERANICO_DELIVERY__CARRIER_BASE_URL                = local.carrier_url
      VERANICO_DELIVERY__INTERNAL_BASE_URL               = local.api_url
      VERANICO_DELIVERY__TASKS_PROJECT                   = var.project_id
      VERANICO_DELIVERY__TASKS_LOCATION                  = google_cloud_tasks_queue.deliveries.location
      VERANICO_DELIVERY__TASKS_QUEUE                     = google_cloud_tasks_queue.deliveries.name
      VERANICO_DELIVERY__ATTEMPT_LIMIT                   = tostring(var.delivery_attempt_limit)
      VERANICO_DELIVERY__RETRY_WINDOW_SECONDS            = tostring(var.delivery_retry_window_seconds)
      VERANICO_DELIVERY__TASKS_DISPATCH_DEADLINE_SECONDS = tostring(var.delivery_dispatch_deadline_seconds)
      VERANICO_DELIVERY__WEBHOOK_TOTAL_TIMEOUT_SECONDS   = tostring(var.webhook_total_timeout_seconds)

      # The internal routes accept only identity tokens of this account for this audience,
      # which are the ones Cloud Tasks and Cloud Scheduler are configured to send.
      VERANICO_DELIVERY__INTERNAL_AUTH      = "oidc"
      VERANICO_DELIVERY__OIDC_AUDIENCE      = local.api_url
      VERANICO_DELIVERY__OIDC_INVOKER_EMAIL = google_service_account.invoker.email
    },
    var.agent_model == null ? {} : { AGENT_MODEL = var.agent_model },
  )

  carrier_env = {
    APP_ROLE                                      = "carrier"
    VERANICO_ENVIRONMENT                          = "production"
    VERANICO_FIRESTORE_PROJECT                    = var.project_id
    VERANICO_TELEMETRY__EXPORTER                  = "cloud_trace"
    VERANICO_DELIVERY__CARRIER_FAIL_FIRST_ATTEMPT = tostring(var.carrier_fail_first_attempt)
  }
}

resource "google_cloud_run_v2_service" "api" {
  project  = var.project_id
  name     = local.api_service
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  # The service holds no data; the configuration may replace or remove it.
  deletion_protection = false

  template {
    service_account = google_service_account.api.email

    # Scale to zero, and never beyond two instances: the ceiling is a cost guardrail.
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = local.image

      ports {
        container_port = local.container_port
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        # CPU is allocated (and billed) only while a request is being served.
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Secret values are read by the service at start from Secret Manager; they are never
      # in this configuration, in the state as values, or in the image.
      dynamic "env" {
        for_each = { for key, secret in local.secrets : key => secret if contains(secret.roles, "api") }
        content {
          name = env.value.env
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this[env.key].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        period_seconds    = 2
        timeout_seconds   = 2
        failure_threshold = 30
      }
    }
  }

  depends_on = [
    module.foundation,
    google_secret_manager_secret_iam_member.accessor,
    google_firestore_database.default,
  ]
}

resource "google_cloud_run_v2_service" "carrier" {
  project  = var.project_id
  name     = local.carrier_service
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  deletion_protection = false

  template {
    service_account = google_service_account.carrier.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = local.image

      ports {
        container_port = local.container_port
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.carrier_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = { for key, secret in local.secrets : key => secret if contains(secret.roles, "carrier") }
        content {
          name = env.value.env
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this[env.key].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        period_seconds    = 2
        timeout_seconds   = 2
        failure_threshold = 30
      }
    }
  }

  depends_on = [
    module.foundation,
    google_secret_manager_secret_iam_member.accessor,
    google_firestore_database.default,
  ]
}

# Both services answer the public internet. The product is public by design (SPEC 10: no
# login). The mock carrier is reached by the API service over HTTPS like a real carrier
# would be, and is protected by what protects a real webhook: the signature and the
# timestamp of every request (SPEC 7). The internal routes of the API are protected in the
# application by the identity token check, not by this binding.
resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = {
    api     = google_cloud_run_v2_service.api
    carrier = google_cloud_run_v2_service.carrier
  }

  project  = each.value.project
  location = each.value.location
  name     = each.value.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Optional custom domain for the API service (SPEC 17: the Cloud Run address comes first).
resource "google_cloud_run_domain_mapping" "api" {
  count = var.custom_domain == null ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = var.custom_domain

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.api.name
  }
}
