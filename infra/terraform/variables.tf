# Inputs. Everything that belongs to the person who deploys has no default: the project,
# the billing account, the budget, the alert address, the repository and the origins that
# may frame the embed. The values go in a file kept outside the repository
# (`-var-file=<owner file>`); none of them is a secret.

variable "project_id" {
  description = "Google Cloud project that holds every resource."
  type        = string
}

variable "region" {
  description = "Region of every regional resource. The specification fixes it (SPEC 17)."
  type        = string
  default     = "us-central1"

  validation {
    condition     = var.region == "us-central1"
    error_message = "Everything runs in us-central1 (SPEC 17): the always-free limits of Cloud Run and Cloud Storage this project relies on are tied to that region."
  }
}

variable "billing_account" {
  description = "Billing account identifier (XXXXXX-XXXXXX-XXXXXX) the budget watches."
  type        = string
}

variable "budget_amount" {
  description = "Monthly budget in whole units of budget_currency. Alerts go out at 50%, 90% and 100%."
  type        = number

  validation {
    condition     = var.budget_amount >= 1 && floor(var.budget_amount) == var.budget_amount
    error_message = "The budget is a whole number of currency units, at least 1."
  }
}

variable "budget_currency" {
  description = "ISO 4217 code of the billing account's currency (a budget must use it)."
  type        = string
}

variable "alert_email" {
  description = "Address that receives the budget alerts."
  type        = string
}

variable "github_repository" {
  description = "The only repository whose workflows may deploy, as owner/name."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Give the repository as owner/name."
  }
}

variable "github_repository_id" {
  description = "Optional numeric identifier of the repository (`gh api repos/<owner>/<name> --jq .id`). When set, the federation requires it in addition to the name, which closes the case of a deleted repository's name being claimed by someone else."
  type        = string
  default     = null
}

variable "frame_ancestors" {
  description = "Origins allowed to frame /embed/map (SPEC 12.5). Empty: no page may frame it."
  type        = list(string)
}

variable "custom_domain" {
  description = "Optional domain mapped to the API service, for example veranico.leohteixeira.com. Null: the Cloud Run address is the address."
  type        = string
  default     = null
}

variable "image_tag" {
  description = "Tag of the image both services run. The deploy workflow sets it to the release tag."
  type        = string
}

variable "agent_model" {
  description = "Model identifier of the agent. Null keeps the default built into the application."
  type        = string
  default     = null
}

# --- Webhook delivery -----------------------------------------------------------------------
# One value feeds both the queue and the application, so they cannot drift apart: the
# queue never stops before the application's attempt limit, and the sweep never abandons a
# delivery the queue is still retrying (SPEC 7).

variable "delivery_attempt_limit" {
  description = "Webhook attempts of one delivery round: the queue's max_attempts and the application's attempt limit."
  type        = number
  default     = 5

  validation {
    condition     = var.delivery_attempt_limit >= 1 && var.delivery_attempt_limit <= 100
    error_message = "Between 1 and 100 attempts."
  }
}

variable "delivery_retry_window_seconds" {
  description = "The queue's whole retry window (max_retry_duration), also the age after which the sweep abandons a silent delivery."
  type        = number
  default     = 3600
}

variable "delivery_dispatch_deadline_seconds" {
  description = "Deadline Cloud Tasks gives one delivery call. It must exceed the webhook total timeout, or the queue cancels a call before its attempt is recorded."
  type        = number
  default     = 30

  validation {
    condition     = var.delivery_dispatch_deadline_seconds > var.webhook_total_timeout_seconds
    error_message = "The dispatch deadline must exceed webhook_total_timeout_seconds."
  }
}

variable "webhook_total_timeout_seconds" {
  description = "Total timeout of one webhook call to the carrier."
  type        = number
  default     = 10
}

variable "sweep_schedule" {
  description = "Cron schedule (UTC) of the outbox sweep. Each run wakes the API service once."
  type        = string
  default     = "*/10 * * * *"
}

variable "carrier_fail_first_attempt" {
  description = "The mock carrier answers the first attempt of each event with 503, so the retry path is visible in the demo (SPEC 7)."
  type        = bool
  default     = true
}
