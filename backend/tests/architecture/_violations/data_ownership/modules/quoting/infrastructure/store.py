"""Breaks data ownership: `quoting` names what `access` and `climate` own.

This docstring may mention access_workspaces: prose in a docstring is not a use.
"""

OWN_COLLECTION = "quoting_quotes"
OWN_PATH = "quoting_quotes/Q-000001/audit"

FOREIGN_COLLECTION = "access_workspaces"
FOREIGN_DOCUMENT_PATH = "access_api_keys/key-1"
FOREIGN_PREFIX = "climate/points/8a2a1072b59ffff"
FOREIGN_UNDECLARED = "assistant_summaries"


def blob_path(workspace_id: str, quote_id: str) -> str:
    return f"documents/{workspace_id}/{quote_id}/term-sheet.pdf"
