"""`request_submission`: ask for a quote to be submitted to a carrier. A person decides.

The tool creates a pending approval and nothing more. No tool approves or rejects: only
`POST /approvals/{id}/decision` from a browser session of the workspace does (SPEC 6).
"""

from collections.abc import Sequence

from veranico.modules.assistant.application.tools.models import (
    RequestSubmissionInput,
    Tool,
    ToolSuccess,
)
from veranico.modules.assistant.contracts import ApprovalRequired
from veranico.modules.quoting.contracts import CarrierInfo, QuotingFacade
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import QuoteId
from veranico.shared.kernel.principal import Principal

DESCRIPTION = (
    "Request submission of a quote to a carrier. This only creates a pending approval: a "
    "person approves or rejects it in the Approvals tab, and you cannot. Never say the "
    "submission was approved or sent. Calling it again for the same quote returns the same "
    "submission. Carriers in the directory: {carriers}. Pass the id; name the carrier to the "
    "user by its name only."
)


def request_submission_tool(
    quoting: QuotingFacade, carriers: Sequence[CarrierInfo]
) -> Tool[RequestSubmissionInput]:
    async def handler(principal: Principal, arguments: RequestSubmissionInput) -> ToolSuccess:
        quote_id = QuoteId(arguments.quote_id)
        submission = await quoting.request_submission(
            principal, quote_id, arguments.carrier_id, actor="agent"
        )
        summary = Coded(
            code="tool.request_submission",
            params={
                "submission_id": submission.submission_id,
                "carrier_id": submission.carrier_id,
            },
        )
        # A repeated call on a quote that was already decided returns the old submission:
        # there is nothing left to approve, so no approval is announced.
        approval = (
            ApprovalRequired(approval_id=submission.submission_id, quote_id=quote_id)
            if submission.decided_at is None
            else None
        )
        return ToolSuccess(output=submission, summary=summary, approval=approval)

    listed = "; ".join(f"`{carrier.carrier_id}` ({carrier.name})" for carrier in carriers)
    schema = RequestSubmissionInput.model_json_schema()
    schema["properties"]["carrier_id"]["enum"] = [carrier.carrier_id for carrier in carriers]
    return Tool(
        name="request_submission",
        description=DESCRIPTION.format(carriers=listed),
        input_model=RequestSubmissionInput,
        handler=handler,
        input_schema=schema,
    )
