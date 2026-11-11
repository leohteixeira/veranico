"""`draft_term_sheet`: render and store the term sheet of a quote in both languages."""

from veranico.modules.assistant.application.tools.models import (
    DraftTermSheetInput,
    TermSheetOutput,
    Tool,
    ToolSuccess,
)
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import QuoteId
from veranico.shared.kernel.principal import Principal

DESCRIPTION = (
    "Render the term sheet of a quote as a PDF in English and in Brazilian Portuguese and store "
    "both. Returns `documents`, one per language, each with the API path it is served from. "
    "The interface shows the downloads in the Quote tab."
)


def draft_term_sheet_tool(documents: DocumentsFacade) -> Tool[DraftTermSheetInput]:
    async def handler(principal: Principal, arguments: DraftTermSheetInput) -> ToolSuccess:
        rendered = await documents.render_term_sheets(
            principal, QuoteId(arguments.quote_id), actor="agent"
        )
        return ToolSuccess(
            output=TermSheetOutput(documents=rendered),
            summary=Coded(code="tool.draft_term_sheet"),
        )

    return Tool(
        name="draft_term_sheet",
        description=DESCRIPTION,
        input_model=DraftTermSheetInput,
        handler=handler,
    )
