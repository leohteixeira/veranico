"""Clean: `access` names only its own collections, and an API path is not a storage prefix."""

COLLECTIONS = ("access_workspaces", "access_api_keys", "access_allowances", "access_spend")
ROUTE = "/api/v1/quotes/{id}/term-sheet.pdf"
EVENT = "quoting.submission_approved"
