# Secret Manager entries. They are created empty: a value is added out of band, read from
# standard input, and never passes through Terraform, its state or the repository:
#
#   gcloud secrets versions add <secret id> --data-file=-
#
# The Earth Engine project and credentials are not here and are in no service's environment:
# they are used only by the offline cube build (SPEC 17, ADR 0019).

locals {
  # Secret id => the environment variable that carries it and the roles that read it.
  secrets = {
    "veranico-anthropic-api-key" = {
      env   = "ANTHROPIC_API_KEY"
      roles = ["api"]
    }
    "veranico-webhook-signing-secret" = {
      env   = "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET"
      roles = ["api", "carrier"] # the API signs, the carrier verifies
    }
    "veranico-cookie-signing-secret" = {
      env   = "VERANICO_COOKIE_SIGNING_SECRET"
      roles = ["api"]
    }
    "veranico-allowance-code" = {
      env   = "VERANICO_ACCESS__ALLOWANCE_CODE"
      roles = ["api"]
    }
    "veranico-ip-hash-salt" = {
      env   = "VERANICO_ACCESS__IP_HASH_SALT"
      roles = ["api"]
    }
  }

  # One binding per (secret, role that reads it): an account reads only its own secrets.
  secret_readers = merge([
    for id, secret in local.secrets : {
      for role in secret.roles : "${id}/${role}" => { secret = id, role = role }
    }
  ]...)
}

resource "google_secret_manager_secret" "this" {
  for_each = local.secrets

  project   = var.project_id
  secret_id = each.key

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [module.foundation]
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.secret_readers

  project   = var.project_id
  secret_id = google_secret_manager_secret.this[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.role == "api" ? google_service_account.api.member : google_service_account.carrier.member
}
