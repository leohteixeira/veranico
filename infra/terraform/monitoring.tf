# Operations, limited to what is free (SPEC 15): one uptime check and one billing budget
# with email alerts. There is no alerting policy.

# The check probes `/health`: Cloud Run reserves some paths ending in "z" and answers
# `/healthz` itself, before the request reaches the container.
resource "google_monitoring_uptime_check_config" "api_health" {
  project      = var.project_id
  display_name = "Veranico API /health"
  timeout      = "10s"

  # The longest interval there is: each check wakes the service, which scales to zero.
  period = "900s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(local.api_url, "https://")
    }
  }

  depends_on = [module.foundation]
}

resource "google_monitoring_notification_channel" "budget_email" {
  project      = var.project_id
  display_name = "Veranico budget alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [module.foundation]
}

# The budget alerts; it does not cap spending. The ceilings that stop spending are in the
# application (model spend) and in the instance limits of the services.
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account
  display_name    = "Veranico monthly budget"

  budget_filter {
    projects        = ["projects/${data.google_project.this.number}"]
    calendar_period = "MONTH"
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.budget_email.id]
    # The billing account's own administrators keep receiving the alerts too.
    disable_default_iam_recipients = false
  }

  depends_on = [module.foundation]
}
