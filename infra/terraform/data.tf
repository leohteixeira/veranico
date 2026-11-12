# State: Firestore in Native mode with its TTL policies, and one private bucket.

resource "google_firestore_database" "default" {
  project = var.project_id
  # The free quota of Firestore applies to the database named "(default)".
  name             = "(default)"
  location_id      = var.region
  type             = "FIRESTORE_NATIVE"
  database_edition = "STANDARD"

  # Removing the database takes a deliberate change here first.
  delete_protection_state = "DELETE_PROTECTION_ENABLED"

  depends_on = [module.foundation]
}

locals {
  # Every collection whose documents carry `expires_at` (contracts section 9). A
  # subcollection is addressed by its own name: `audit` under `quoting_quotes`, `messages`
  # under `assistant_conversations`. `access_spend` is the spend ledger and never expires.
  ttl_collections = [
    "access_workspaces",
    "access_api_keys",
    "access_allowances",
    "quoting_quotes",
    "audit",
    "quoting_idempotency",
    "quoting_outbox",
    "assistant_conversations",
    "messages",
    "carriers_receipts",
  ]
}

# TTL deletes a document some time after `expires_at` passes (within about a day), so the
# application also filters on the field. `index_config` is left out on purpose: an empty
# block would switch off the single-field indexes of `expires_at`, which a query filtering
# on the field needs.
resource "google_firestore_field" "ttl" {
  for_each = toset(local.ttl_collections)

  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = each.value
  field      = "expires_at"

  ttl_config {}
}

# Composite indexes: none yet. The emulator runs any valid query without one, so the
# indexes the modules need are added here from their handoffs and proven on the deployed
# service (gate H2).

resource "google_storage_bucket" "data" {
  project  = var.project_id
  name     = "${var.project_id}-veranico"
  location = var.region

  storage_class = "STANDARD"

  # Private: access only through IAM, never through object ACLs, and no public grant can
  # be added later. Objects are served through the API (SPEC 8).
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Weather cubes are built offline and uploaded once; an accidental destroy must not
  # take them along.
  force_destroy = false

  depends_on = [module.foundation]
}
