# Webhook delivery: the Cloud Tasks queue and the Cloud Scheduler sweep (SPEC 7).

resource "google_cloud_tasks_queue" "deliveries" {
  project  = var.project_id
  name     = "veranico-deliveries"
  location = var.region

  # How Cloud Tasks reads the two limits (RetryConfig reference): `max_attempts` counts
  # the first attempt, and the queue stops retrying a task only when the attempts AND the
  # duration are both exhausted. With the backoff below, the attempts of one round take a
  # few minutes, so the duration is what ends a task: it is the queue's whole retry window.
  # The application gives up on a delivery at the same attempt limit and treats a delivery
  # silent for longer than the same window as abandoned, so neither side outlasts the other.
  retry_config {
    max_attempts       = var.delivery_attempt_limit
    max_retry_duration = "${var.delivery_retry_window_seconds}s"
    min_backoff        = "10s"
    max_backoff        = "300s"
    max_doublings      = 4
  }

  # A demo sends a handful of webhooks; the limits keep a mistake from fanning out.
  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = 5
  }

  # The dispatch deadline is a property of each task, not of the queue: the application
  # sets it from VERANICO_DELIVERY__TASKS_DISPATCH_DEADLINE_SECONDS (services.tf).

  depends_on = [module.foundation]
}

# The sweep finds events that were committed but never enqueued (a crash in between) and
# abandons deliveries that went silent. It calls the API service as the invoker account;
# the service checks that identity itself.
resource "google_cloud_scheduler_job" "outbox_sweep" {
  project     = var.project_id
  name        = "veranico-outbox-sweep"
  region      = var.region
  description = "Enqueue committed outbox events that were never enqueued."

  schedule         = var.sweep_schedule
  time_zone        = "Etc/UTC"
  attempt_deadline = "60s"

  http_target {
    http_method = "POST"
    uri         = "${local.api_url}/api/v1/internal/outbox/sweep"

    oidc_token {
      service_account_email = google_service_account.invoker.email
      audience              = local.api_url
    }
  }

  # A missed run is made up by the next one; do not pile retries on a cold start.
  retry_config {
    retry_count = 1
  }

  depends_on = [module.foundation]
}
