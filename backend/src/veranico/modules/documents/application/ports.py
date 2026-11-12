"""Ports of `documents`, declared by the application layer and implemented in infrastructure."""

from typing import Protocol

from veranico.modules.documents.application.content import TermSheetContent
from veranico.shared.kernel.ids import Locale


class TermSheetRenderer(Protocol):
    def render(self, content: TermSheetContent, locale: Locale) -> bytes:
        """The PDF of the content in one locale. Equal content and locale give equal bytes."""
        ...
