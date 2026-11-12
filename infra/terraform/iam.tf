# Runtime identities: one account per role, each with only what that role uses, and one
# account that Cloud Tasks and Cloud Scheduler call the API as. No account has a key.

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "veranico-api"
  display_name = "Veranico API role"

  depends_on = [module.foundation]
}

resource "google_service_account" "carrier" {
  project      = var.project_id
  account_id   = "veranico-carrier"
  display_name = "Veranico mock carrier role"

  depends_on = [module.foundation]
}

resource "google_service_account" "invoker" {
  project      = var.project_id
  account_id   = "veranico-invoker"
  display_name = "Identity of Cloud Tasks and Cloud Scheduler calls to the API"

  depends_on = [module.foundation]
}

locals {
  # Project-level roles of the runtime accounts. Firestore has no narrower grant than the
  # database: collection ownership per module is kept by the application (SPEC 14).
  runtime_roles = {
    "api/datastore"     = { member = google_service_account.api.member, role = "roles/datastore.user" }
    "api/trace"         = { member = google_service_account.api.member, role = "roles/cloudtrace.agent" }
    "carrier/datastore" = { member = google_service_account.carrier.member, role = "roles/datastore.user" }
    "carrier/trace"     = { member = google_service_account.carrier.member, role = "roles/cloudtrace.agent" }
  }
}

resource "google_project_iam_member" "runtime" {
  for_each = local.runtime_roles

  project = var.project_id
  role    = each.value.role
  member  = each.value.member
}

# The API role reads and writes objects of the one bucket. The carrier has no storage role.
resource "google_storage_bucket_iam_member" "api_objects" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectUser"
  member = google_service_account.api.member
}

# The API role adds tasks to the delivery queue, and only to that queue.
resource "google_cloud_tasks_queue_iam_member" "api_enqueues" {
  project  = google_cloud_tasks_queue.deliveries.project
  location = google_cloud_tasks_queue.deliveries.location
  name     = google_cloud_tasks_queue.deliveries.name
  role     = "roles/cloudtasks.enqueuer"
  member   = google_service_account.api.member
}

# A task carries an identity token of the invoker account; creating such a task requires
# permission to act as that account.
resource "google_service_account_iam_member" "api_uses_invoker" {
  service_account_id = google_service_account.invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.api.member
}
