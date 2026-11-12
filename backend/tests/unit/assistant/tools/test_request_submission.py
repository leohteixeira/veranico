import pytest

from tests.unit.assistant.tools.kit import BROWSER, OTHER, build_kit
from veranico.modules.assistant.contracts import ApprovalRequired
from veranico.modules.quoting.contracts import Decision
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import QuoteId, SubmissionId

pytestmark = [pytest.mark.req("R-9.4-7"), pytest.mark.req("R-9.4-8")]


async def test_maps_arguments_to_the_facade_call() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()
    kit.quoting.calls.clear()

    await kit.registry.execute(
        BROWSER, "request_submission", {"quote_id": quote_id, "carrier_id": "carrier-2"}
    )

    assert kit.quoting.calls == [("request_submission", (BROWSER, quote_id, "carrier-2", "agent"))]


async def test_returns_the_output_model_serialised() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()

    outcome = await kit.registry.execute(
        BROWSER, "request_submission", {"quote_id": quote_id, "carrier_id": "carrier-1"}
    )

    quote = await kit.quoting.get_quote(BROWSER, QuoteId(quote_id))
    assert quote.submission is not None
    assert outcome.ok
    assert outcome.result == quote.submission.model_dump(mode="json")
    assert outcome.summary == Coded(
        code="tool.request_submission",
        params={"submission_id": quote.submission.submission_id, "carrier_id": "carrier-1"},
    )
    assert quote.status == "pending_approval"


async def test_request_submission_emits_approval_and_is_idempotent_per_quote() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()
    arguments = {"quote_id": quote_id, "carrier_id": "carrier-1"}

    first = await kit.registry.execute(BROWSER, "request_submission", arguments)
    second = await kit.registry.execute(BROWSER, "request_submission", arguments)

    assert first.result is not None
    submission_id = SubmissionId(str(first.result["submission_id"]))
    assert first.approval == ApprovalRequired(approval_id=submission_id, quote_id=QuoteId(quote_id))
    assert second.result == first.result
    assert second.approval == first.approval
    assert len(await kit.quoting.list_approvals(BROWSER, None)) == 1


@pytest.mark.req("R-9.3-3")
async def test_a_decided_submission_announces_no_approval_and_stays_decided() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()
    arguments = {"quote_id": quote_id, "carrier_id": "carrier-1"}
    first = await kit.registry.execute(BROWSER, "request_submission", arguments)
    assert first.approval is not None
    await kit.quoting.decide(BROWSER, first.approval.approval_id, Decision(approve=False))

    again = await kit.registry.execute(BROWSER, "request_submission", arguments)

    assert again.ok
    assert again.approval is None
    assert (await kit.quoting.get_quote(BROWSER, QuoteId(quote_id))).status == "rejected"


async def test_the_carrier_list_of_the_definition_comes_from_the_catalogue() -> None:
    kit = build_kit()

    [definition] = [d for d in kit.registry.definitions() if d.name == "request_submission"]

    properties = definition.input_schema["properties"]
    assert isinstance(properties, dict)
    assert properties["carrier_id"]["enum"] == ["carrier-1", "carrier-2"]
    assert (
        "`carrier-1` (Fake Carrier One); `carrier-2` (Fake Carrier Two)" in definition.description
    )
    assert ("catalog", ()) in kit.carriers.calls


async def test_quote_of_another_workspace_is_not_found() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()

    outcome = await kit.registry.execute(
        OTHER, "request_submission", {"quote_id": quote_id, "carrier_id": "carrier-1"}
    )

    assert outcome.error is not None
    assert outcome.error.error_code == "not_found"
    assert outcome.approval is None
