# Guardrails of SPEC 17, asserted on the planned resources.
#
#   terraform -chdir=infra/terraform init -backend=false
#   terraform -chdir=infra/terraform test
#
# No project, no credentials and no network call to Google are involved: the provider is
# mocked (Terraform 1.7 or later), every run only plans, and nothing is created. The few
# attributes a real provider computes and the assertions compare (account identities, the
# project number, the alert channel) are given fixed stand-in values below, available at
# plan time.
#
# Two guardrails are absences, which a plan cannot assert, and are covered by the static
# check `.github/scripts/check_delivery.py terraform-keys`: no service account key resource
# and no secret version (a secret value) anywhere in this configuration.

mock_provider "google" {}

override_data {
  target          = data.google_project.this
  override_during = plan
  values = {
    number = "123456789012"
  }
}

override_resource {
  target          = google_service_account.api
  override_during = plan
  values = {
    name   = "projects/veranico-test/serviceAccounts/veranico-api@veranico-test.iam.gserviceaccount.com"
    email  = "veranico-api@veranico-test.iam.gserviceaccount.com"
    member = "serviceAccount:veranico-api@veranico-test.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.carrier
  override_during = plan
  values = {
    name   = "projects/veranico-test/serviceAccounts/veranico-carrier@veranico-test.iam.gserviceaccount.com"
    email  = "veranico-carrier@veranico-test.iam.gserviceaccount.com"
    member = "serviceAccount:veranico-carrier@veranico-test.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.invoker
  override_during = plan
  values = {
    name   = "projects/veranico-test/serviceAccounts/veranico-invoker@veranico-test.iam.gserviceaccount.com"
    email  = "veranico-invoker@veranico-test.iam.gserviceaccount.com"
    member = "serviceAccount:veranico-invoker@veranico-test.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_monitoring_notification_channel.budget_email
  override_during = plan
  values = {
    id = "projects/veranico-test/notificationChannels/1"
  }
}

# Stand-ins for the values that belong to the person who deploys. None is real.
variables {
  project_id        = "veranico-test"
  billing_account   = "000000-000000-000000"
  budget_amount     = 25
  budget_currency   = "USD"
  alert_email       = "alerts@example.com"
  github_repository = "example-owner/veranico"
  frame_ancestors   = ["https://portfolio.example"]
  image_tag         = "v0.0.0-test"
}

run "services_scale_from_zero_to_two" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.api.template[0].scaling[0].min_instance_count == 0
    error_message = "The API service must scale to zero."
  }
  assert {
    condition     = google_cloud_run_v2_service.api.template[0].scaling[0].max_instance_count == 2
    error_message = "The API service must be limited to 2 instances."
  }
  assert {
    condition     = google_cloud_run_v2_service.carrier.template[0].scaling[0].min_instance_count == 0
    error_message = "The carrier service must scale to zero."
  }
  assert {
    condition     = google_cloud_run_v2_service.carrier.template[0].scaling[0].max_instance_count == 2
    error_message = "The carrier service must be limited to 2 instances."
  }
  assert {
    condition = alltrue([
      for service in [google_cloud_run_v2_service.api, google_cloud_run_v2_service.carrier] :
      service.template[0].containers[0].resources[0].cpu_idle
    ])
    error_message = "CPU must be allocated only while a request is served."
  }
}

run "no_domain_is_mapped_unless_one_is_given" {
  command = plan

  assert {
    condition     = length(google_cloud_run_domain_mapping.api) == 0
    error_message = "Without custom_domain the Cloud Run address is the address: no mapping."
  }
}

run "a_given_domain_is_mapped_to_the_api_service" {
  command = plan

  variables {
    custom_domain = "veranico.leohteixeira.com"
  }

  assert {
    condition     = length(google_cloud_run_domain_mapping.api) == 1
    error_message = "A given custom_domain must produce one domain mapping."
  }
  assert {
    condition     = google_cloud_run_domain_mapping.api[0].name == "veranico.leohteixeira.com"
    error_message = "The mapping must be for the given domain."
  }
  assert {
    condition     = google_cloud_run_domain_mapping.api[0].spec[0].route_name == google_cloud_run_v2_service.api.name
    error_message = "The domain must point at the API service."
  }
}

run "every_regional_resource_is_in_us_central1" {
  command = plan

  assert {
    condition = alltrue([
      for location in [
        google_cloud_run_v2_service.api.location,
        google_cloud_run_v2_service.carrier.location,
        google_firestore_database.default.location_id,
        google_storage_bucket.data.location,
        google_cloud_tasks_queue.deliveries.location,
        google_cloud_scheduler_job.outbox_sweep.region,
      ] : lower(location) == "us-central1"
    ])
    error_message = "Services, database, bucket, queue and scheduler job must all be in us-central1."
  }
  assert {
    condition = alltrue(flatten([
      for secret in google_secret_manager_secret.this : [
        for replica in secret.replication[0].user_managed[0].replicas : replica.location == "us-central1"
      ]
    ]))
    error_message = "Every secret must be replicated in us-central1 only."
  }
  assert {
    condition     = startswith(module.foundation.registry, "us-central1-docker.pkg.dev/")
    error_message = "The image registry must be in us-central1."
  }
}

run "another_region_is_rejected" {
  command = plan

  variables {
    region = "europe-west1"
  }

  expect_failures = [var.region]
}

# Public through the disabled invoker check, never through an `allUsers` binding: the
# organization's domain restricted sharing refuses `allUsers` (see services.tf).
run "services_are_public_without_an_all_users_binding" {
  command = plan

  assert {
    condition = alltrue([
      for service in [google_cloud_run_v2_service.api, google_cloud_run_v2_service.carrier] :
      service.invoker_iam_disabled == true
    ])
    error_message = "Both services must be public through invoker_iam_disabled = true."
  }
}

run "bucket_is_private" {
  command = plan

  assert {
    condition     = google_storage_bucket.data.public_access_prevention == "enforced"
    error_message = "The bucket must enforce public access prevention."
  }
  assert {
    condition     = google_storage_bucket.data.uniform_bucket_level_access == true
    error_message = "The bucket must use uniform bucket-level access (no object ACLs)."
  }
  assert {
    condition     = !contains(["allUsers", "allAuthenticatedUsers"], google_storage_bucket_iam_member.api_objects.member)
    error_message = "The bucket must have no binding for all users."
  }
  assert {
    condition     = google_storage_bucket_iam_member.api_objects.member == google_service_account.api.member
    error_message = "Only the API role's account may be bound on the bucket."
  }
}

# The names are written out here, not read from the configuration: removing a collection
# from `local.ttl_collections` must fail this run. They are the names the stores use
# (`audit` and `messages` are subcollections, so they need a policy of their own: deleting
# a parent document does not delete its subcollections).
run "every_expiring_collection_has_a_ttl_policy" {
  command = plan

  assert {
    condition = toset(keys(google_firestore_field.ttl)) == toset([
      "access_workspaces",
      "access_api_keys",
      "access_allowances",
      "quoting_quotes",
      "audit",
      "quoting_idempotency",
      "quoting_outbox",
      "carriers_receipts",
      "assistant_conversations",
      "messages",
    ])
    error_message = "The TTL policies must cover exactly the collections whose documents carry expires_at."
  }
  assert {
    condition     = alltrue([for name, field in google_firestore_field.ttl : field.collection == name && field.field == "expires_at"])
    error_message = "Every TTL policy must be on the field expires_at of its own collection."
  }
  assert {
    condition     = alltrue([for field in google_firestore_field.ttl : length(field.ttl_config) == 1])
    error_message = "Every expiring collection must have the TTL configuration block."
  }
  assert {
    condition     = alltrue([for field in google_firestore_field.ttl : length(field.index_config) == 0])
    error_message = "A TTL policy must not carry index_config: an empty block switches off the single-field indexes of expires_at."
  }
}

run "registry_keeps_the_last_three_images" {
  command = plan

  module {
    source = "./foundation"
  }

  variables {
    region = "us-central1"
  }

  assert {
    condition = [
      for policy in google_artifact_registry_repository.images.cleanup_policies :
      policy.most_recent_versions[0].keep_count if policy.action == "KEEP"
    ] == [3]
    error_message = "The registry must have exactly one keep policy, keeping the 3 most recent versions."
  }
  assert {
    condition = length([
      for policy in google_artifact_registry_repository.images.cleanup_policies :
      policy if policy.action == "DELETE" && policy.condition[0].tag_state == "ANY"
    ]) == 1
    error_message = "A keep policy deletes nothing by itself: the delete-everything policy must be present."
  }
  assert {
    condition     = google_artifact_registry_repository.images.cleanup_policy_dry_run != true
    error_message = "The cleanup policy must not be in dry-run mode."
  }
}

run "federation_is_restricted_to_one_repository" {
  command = plan

  module {
    source = "./foundation"
  }

  variables {
    region = "us-central1"
  }

  override_resource {
    target          = google_iam_workload_identity_pool.github
    override_during = plan
    values = {
      name = "projects/123456789012/locations/global/workloadIdentityPools/github"
    }
  }

  override_resource {
    target          = google_service_account.deployer
    override_during = plan
    values = {
      name   = "projects/veranico-test/serviceAccounts/veranico-deployer@veranico-test.iam.gserviceaccount.com"
      email  = "veranico-deployer@veranico-test.iam.gserviceaccount.com"
      member = "serviceAccount:veranico-deployer@veranico-test.iam.gserviceaccount.com"
    }
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.github.attribute_condition == "assertion.repository == \"example-owner/veranico\""
    error_message = "The federation provider must refuse tokens of every other repository."
  }
  assert {
    condition     = google_iam_workload_identity_pool_provider.github.oidc[0].issuer_uri == "https://token.actions.githubusercontent.com"
    error_message = "The federation provider must trust GitHub's token issuer only."
  }
  assert {
    condition     = endswith(google_service_account_iam_member.deployer_from_repository.member, "/attribute.repository/example-owner/veranico")
    error_message = "Only identities of the one repository may act as the deployer."
  }
  assert {
    condition     = google_service_account_iam_member.deployer_from_repository.role == "roles/iam.workloadIdentityUser"
    error_message = "The repository reaches the deployer through workload identity, not through a key."
  }
}

run "federation_also_requires_the_repository_id_when_given" {
  command = plan

  module {
    source = "./foundation"
  }

  variables {
    region               = "us-central1"
    github_repository_id = "123456789"
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.github.attribute_condition == "assertion.repository == \"example-owner/veranico\" && assertion.repository_id == \"123456789\""
    error_message = "With a repository id, the federation must require the name and the id."
  }
}

run "deployer_has_no_primitive_role" {
  command = plan

  module {
    source = "./foundation"
  }

  variables {
    region = "us-central1"
  }

  assert {
    condition = alltrue([
      for binding in google_project_iam_member.deployer :
      !contains(["roles/owner", "roles/editor", "roles/viewer"], binding.role)
    ])
    error_message = "The deployer must hold no primitive role (owner, editor, viewer)."
  }
  assert {
    condition     = length(google_project_iam_member.deployer) > 0
    error_message = "The deployer's roles must be listed one by one."
  }
}

run "five_secrets_and_each_role_reads_only_its_own" {
  command = plan

  assert {
    condition = toset(keys(google_secret_manager_secret.this)) == toset([
      "veranico-anthropic-api-key",
      "veranico-webhook-signing-secret",
      "veranico-cookie-signing-secret",
      "veranico-allowance-code",
      "veranico-ip-hash-salt",
    ])
    error_message = "Exactly the five secrets of SPEC 17 must exist."
  }
  assert {
    condition = toset([
      for binding in google_secret_manager_secret_iam_member.accessor :
      binding.secret_id if binding.member == google_service_account.carrier.member
    ]) == toset(["veranico-webhook-signing-secret"])
    error_message = "The carrier role may read the webhook signing secret and nothing else."
  }
  assert {
    condition = alltrue([
      for env in google_cloud_run_v2_service.api.template[0].containers[0].env :
      length(env.value_source) == 1
      if contains(["ANTHROPIC_API_KEY", "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET", "VERANICO_COOKIE_SIGNING_SECRET", "VERANICO_ACCESS__ALLOWANCE_CODE", "VERANICO_ACCESS__IP_HASH_SALT"], env.name)
    ])
    error_message = "A secret reaches the service as a Secret Manager reference, never as a literal value."
  }
  assert {
    condition = length([
      for env in google_cloud_run_v2_service.api.template[0].containers[0].env :
      env.name if length(env.value_source) == 1
    ]) == 5
    error_message = "The API service must reference all five secrets."
  }
}

run "cube_build_credentials_never_reach_a_service" {
  command = plan

  assert {
    condition = alltrue([
      for env in setunion(
        google_cloud_run_v2_service.api.template[0].containers[0].env,
        google_cloud_run_v2_service.carrier.template[0].containers[0].env,
        ) : !anytrue([
          for word in ["CDS", "EARTHENGINE", "GOOGLE_APPLICATION_CREDENTIALS"] :
          strcontains(upper(env.name), word)
      ])
    ])
    error_message = "The cube build's Earth Engine project and credentials belong to the offline build and must not be in a service's environment."
  }
}

run "uptime_check_and_budget_exist" {
  command = plan

  assert {
    condition     = google_monitoring_uptime_check_config.api_health.http_check[0].path == "/healthz"
    error_message = "The uptime check must probe /healthz."
  }
  assert {
    condition     = google_monitoring_uptime_check_config.api_health.http_check[0].use_ssl == true
    error_message = "The uptime check must use HTTPS."
  }
  assert {
    condition     = google_billing_budget.monthly.amount[0].specified_amount[0].units == "25"
    error_message = "The budget amount must come from the budget variable."
  }
  assert {
    condition     = contains([for rule in google_billing_budget.monthly.threshold_rules : rule.threshold_percent], 1)
    error_message = "The budget must alert when the whole amount is spent."
  }
  assert {
    condition     = google_billing_budget.monthly.all_updates_rule[0].monitoring_notification_channels == tolist([google_monitoring_notification_channel.budget_email.id])
    error_message = "The budget must send its alerts to the email channel."
  }
  assert {
    condition     = google_monitoring_notification_channel.budget_email.type == "email" && google_monitoring_notification_channel.budget_email.labels["email_address"] == "alerts@example.com"
    error_message = "The alert channel must be the configured email address."
  }
}

run "queue_and_application_share_their_limits" {
  command = plan

  variables {
    delivery_attempt_limit        = 7
    delivery_retry_window_seconds = 1800
  }

  assert {
    condition     = google_cloud_tasks_queue.deliveries.retry_config[0].max_attempts == 7
    error_message = "The queue's attempt limit must come from the delivery variable."
  }
  assert {
    condition     = google_cloud_tasks_queue.deliveries.retry_config[0].max_retry_duration == "1800s"
    error_message = "The queue's retry window must come from the delivery variable."
  }
  assert {
    condition = one([
      for env in google_cloud_run_v2_service.api.template[0].containers[0].env :
      env.value if env.name == "VERANICO_DELIVERY__ATTEMPT_LIMIT"
    ]) == "7"
    error_message = "The application's attempt limit must equal the queue's."
  }
  assert {
    condition = one([
      for env in google_cloud_run_v2_service.api.template[0].containers[0].env :
      env.value if env.name == "VERANICO_DELIVERY__RETRY_WINDOW_SECONDS"
    ]) == "1800"
    error_message = "The application's retry window must equal the queue's."
  }
}

run "internal_callers_use_the_identity_the_service_checks" {
  command = plan

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.api.template[0].containers[0].env :
      env.value if env.name == "VERANICO_DELIVERY__OIDC_INVOKER_EMAIL"
    ]) == google_cloud_scheduler_job.outbox_sweep.http_target[0].oidc_token[0].service_account_email
    error_message = "The scheduler must call as the account the API service accepts."
  }
  assert {
    condition = one([
      for env in google_cloud_run_v2_service.api.template[0].containers[0].env :
      env.value if env.name == "VERANICO_DELIVERY__OIDC_AUDIENCE"
    ]) == google_cloud_scheduler_job.outbox_sweep.http_target[0].oidc_token[0].audience
    error_message = "The scheduler's token audience must be the one the API service accepts."
  }
  assert {
    condition     = endswith(google_cloud_scheduler_job.outbox_sweep.http_target[0].uri, "/api/v1/internal/outbox/sweep")
    error_message = "The scheduler must call the sweep route."
  }
  assert {
    condition = one([
      for env in google_cloud_run_v2_service.api.template[0].containers[0].env :
      env.value if env.name == "VERANICO_DELIVERY__INTERNAL_AUTH"
    ]) == "oidc"
    error_message = "The internal routes must require an identity token in production."
  }
}

run "dispatch_deadline_must_exceed_the_webhook_timeout" {
  command = plan

  variables {
    delivery_dispatch_deadline_seconds = 10
    webhook_total_timeout_seconds      = 10
  }

  expect_failures = [var.delivery_dispatch_deadline_seconds]
}
