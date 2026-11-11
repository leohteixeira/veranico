"""Bodies that exist only on the wire of the `quoting` routes."""

from pydantic import BaseModel


class SubmissionRequest(BaseModel, frozen=True):
    carrier_id: str


class SweepResult(BaseModel, frozen=True):
    enqueued: int
