"""Who is acting on a workspace."""

from typing import Literal

from pydantic import BaseModel

from veranico.shared.kernel.ids import WorkspaceId


class Principal(BaseModel, frozen=True):
    workspace_id: WorkspaceId
    kind: Literal["browser", "api_key", "system"]
    key_id: str | None = None
