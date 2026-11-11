# What must exist before the first workflow run.
#
# The first apply has an ordering problem: the services need an image, the image needs the
# registry, and the workflow that pushes it needs the federation. This module holds exactly
# those prerequisites, so one targeted apply by the owner solves it without conditional
# resources anywhere:
#
#   terraform apply -target=module.foundation -var-file=<owner file>
#
# After that the deploy workflow applies the whole configuration.

terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
    }
  }
}

locals {
  # One entry per product the configuration uses; nothing is enabled "just in case".
  services = [
    "artifactregistry.googleapis.com",     # the image registry
    "billingbudgets.googleapis.com",       # the budget
    "cloudresourcemanager.googleapis.com", # project IAM, read by Terraform
    "cloudscheduler.googleapis.com",       # the outbox sweep
    "cloudtasks.googleapis.com",           # webhook delivery
    "cloudtrace.googleapis.com",           # traces
    "firestore.googleapis.com",            # state
    "iam.googleapis.com",                  # service accounts, federation
    "iamcredentials.googleapis.com",       # short-lived tokens for the federated deployer
    "monitoring.googleapis.com",           # the uptime check, the alert address
    "run.googleapis.com",                  # both services
    "secretmanager.googleapis.com",        # the five secrets
    "serviceusage.googleapis.com",         # enabling the services above
    "storage.googleapis.com",              # the bucket
    "sts.googleapis.com",                  # token exchange of the federation
  ]

  # Roles of the account the deploy workflow acts as, one line per thing it manages with
  # `terraform apply`. There is no primitive role (owner, editor, viewer) and there never
  # is a key: the account is reachable only through the federation below.
  #
  # Two of them are broad by nature and are stated plainly. `projectIamAdmin` lets the
  # account grant roles in this project, which Terraform needs to bind the runtime
  # accounts; `secretmanager.admin` is the only predefined role that can create a secret
  # and set its access policy, and it can also read secret values. Both are confined by who
  # can become the account: workflows of one repository.
  deployer_roles = [
    "roles/artifactregistry.admin",          # push images, keep the cleanup policy
    "roles/cloudscheduler.admin",            # the sweep job
    "roles/cloudtasks.admin",                # the delivery queue
    "roles/datastore.owner",                 # the database and its TTL policies
    "roles/iam.serviceAccountAdmin",         # the runtime accounts
    "roles/iam.serviceAccountUser",          # deploy services that run as them
    "roles/iam.workloadIdentityPoolAdmin",   # this federation
    "roles/monitoring.editor",               # the uptime check and the alert address
    "roles/resourcemanager.projectIamAdmin", # role bindings of the runtime accounts
    "roles/run.admin",                       # both services
    "roles/secretmanager.admin",             # the secret entries and who may read them
    "roles/serviceusage.serviceUsageAdmin",  # the enabled services
    "roles/storage.admin",                   # the bucket and the Terraform state bucket
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project = var.project_id
  service = each.value

  # Destroying this configuration must not switch a service off under other resources.
  disable_on_destroy = false
}

# --- Image registry -------------------------------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "veranico"
  format        = "DOCKER"
  description   = "Container images of Veranico (one image, both roles)."

  # Keep the last 3 images (SPEC 17). A keep policy alone deletes nothing: it protects what
  # a delete policy would remove, so the pair below means "delete everything except the 3
  # most recent versions" (Artifact Registry documentation, cleanup policies).
  cleanup_policies {
    id     = "delete-all"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }
  cleanup_policies {
    id     = "keep-last-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  depends_on = [google_project_service.enabled]
}

# --- Workload Identity Federation for GitHub Actions ----------------------------------------
# The workflow proves who it is with the OIDC token GitHub issues for the run; Google
# exchanges it for a short-lived token of the deployer account. No key file exists.

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Tokens of any other repository are refused at the exchange, before any role is looked
  # at. Without a condition every repository on GitHub could present a token here. A name
  # can be claimed again after a repository is deleted; the numeric identifier cannot, so
  # it is added to the condition when the owner supplies it.
  attribute_condition = join(" && ", compact([
    "assertion.repository == \"${var.github_repository}\"",
    var.github_repository_id == null ? "" : "assertion.repository_id == \"${var.github_repository_id}\"",
  ]))
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "veranico-deployer"
  display_name = "Veranico deployer (GitHub Actions, through federation)"

  depends_on = [google_project_service.enabled]
}

resource "google_service_account_iam_member" "deployer_from_repository" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_project_iam_member" "deployer" {
  for_each = toset(local.deployer_roles)

  project = var.project_id
  role    = each.value
  member  = google_service_account.deployer.member
}

# The budget lives on the billing account, not in the project.
resource "google_billing_account_iam_member" "deployer_budgets" {
  billing_account_id = var.billing_account
  role               = "roles/billing.costsManager"
  member             = google_service_account.deployer.member
}
