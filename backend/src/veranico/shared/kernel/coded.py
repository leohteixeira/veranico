"""Translatable text: a code plus parameters, never prose."""

from pydantic import BaseModel


class Coded(BaseModel, frozen=True):
    code: str
    params: dict[str, str | int | float] = {}
