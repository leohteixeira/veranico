import pytest

from tests.api.quoting.conftest import V1, QuotingApi, quote_body
from tests.fakes import builders
from veranico.shared.kernel.errors import OutsideCoverageError

pytestmark = pytest.mark.integration

KEY = {"Idempotency-Key": "request-1"}


@pytest.mark.req("R-6-4")
@pytest.mark.req("R-11.1-1")
async def test_a_quote_cannot_be_created_without_an_idempotency_key(api: QuotingApi) -> None:
    session = await api.session()

    missing = await session.api.post(f"{V1}/quotes", json=quote_body())
    blank = await session.api.post(
        f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": "  "}
    )

    for response in (missing, blank):
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_arguments"
    assert (await session.browser.get(f"{V1}/quotes")).json() == []
    assert api.pricing.calls == []


@pytest.mark.req("R-6-4")
@pytest.mark.req("R-6-1")
@pytest.mark.req("R-11.1-1")
async def test_a_quote_is_priced_from_coordinates_alone(api: QuotingApi) -> None:
    session = await api.session()
    body = quote_body(label="Fazenda Santa Luzia")

    response = await session.api.post(f"{V1}/quotes", json=body, headers=KEY)

    assert response.status_code == 200
    quote = response.json()
    assert quote["status"] == "draft"
    assert quote["workspace_id"] == session.workspace_id
    assert quote["submission"] is None
    # The grid cell and the dataset are what `climate` answered for the coordinates.
    assert ("resolve_location", (None, builders.LAT, builders.LON)) in api.climate.calls
    assert ("ensure_history", (builders.LAT, builders.LON)) in api.climate.calls
    assert quote["dataset_id"] == builders.point_dataset_for(builders.LAT, builders.LON)
    assert quote["location"] == {
        "label": "Fazenda Santa Luzia",
        "lat": builders.LAT,
        "lon": builders.LON,
        "h3_cell": builders.h3_cell_for(builders.LAT, builders.LON),
        "admin_region": None,
    }
    assert quote["cover"] == body["cover"]
    premium = quote["priced"]["premium"]
    assert isinstance(premium["premium"]["amount_cents"], int)
    assert isinstance(premium["rate_on_line"], str)
    assert quote["priced"]["simulation"]["n"] == 1_000
    (entry,) = quote["audit"]
    assert entry["actor"] == "api_client"
    assert entry["action"]["code"] == "audit.quote_created"
    assert entry["action"]["params"] == {"key_id": "key-1"}


@pytest.mark.req("R-6-4")
async def test_a_grid_cell_or_dataset_sent_by_the_client_is_not_used(api: QuotingApi) -> None:
    session = await api.session()
    body = quote_body(h3_cell="86a8100c7ffffff")
    body["dataset_id"] = "point:86a8100c7ffffff"

    response = await session.api.post(f"{V1}/quotes", json=body, headers=KEY)

    quote = response.json()
    assert response.status_code == 200
    assert quote["dataset_id"] == builders.point_dataset_for(builders.LAT, builders.LON)
    assert quote["location"]["h3_cell"] == builders.h3_cell_for(builders.LAT, builders.LON)
    assert quote["location"]["label"] == "-12.5500, -55.7200"


@pytest.mark.req("R-6-4")
async def test_a_replay_returns_the_same_body_and_another_payload_is_a_conflict(
    api: QuotingApi,
) -> None:
    session = await api.session()
    first = await session.api.post(f"{V1}/quotes", json=quote_body(), headers=KEY)
    priced = len(api.pricing.calls)

    replay = await session.api.post(f"{V1}/quotes", json=quote_body(), headers=KEY)
    conflict = await session.api.post(
        f"{V1}/quotes", json=quote_body(lat=builders.LAT + 0.5), headers=KEY
    )
    other_key = await session.api.post(
        f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": "request-2"}
    )

    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert other_key.json()["quote_id"] != first.json()["quote_id"]
    assert len(api.pricing.calls) == priced + 1  # only the new key was priced
    assert len((await session.browser.get(f"{V1}/quotes")).json()) == 2


@pytest.mark.req("R-11.2-4")
@pytest.mark.req("R-11.1-2")
async def test_a_cookie_session_lists_and_reads_the_quotes_its_api_key_created(
    api: QuotingApi,
) -> None:
    session = await api.session()
    created = (await session.api.post(f"{V1}/quotes", json=quote_body(), headers=KEY)).json()

    listed = await session.browser.get(f"{V1}/quotes")
    by_cookie = await session.browser.get(f"{V1}/quotes/{created['quote_id']}")
    by_key = await session.api.get(f"{V1}/quotes/{created['quote_id']}")

    assert listed.status_code == 200
    assert listed.json() == [
        {
            "quote_id": created["quote_id"],
            "created_at": created["created_at"],
            "status": "draft",
            "location_label": created["location"]["label"],
            "premium": created["priced"]["premium"]["premium"],
        }
    ]
    assert by_cookie.json() == by_key.json() == created


async def test_creating_a_quote_needs_an_api_key(api: QuotingApi) -> None:
    session = await api.session()

    by_cookie = await session.browser.post(f"{V1}/quotes", json=quote_body(), headers=KEY)
    bad_key = await api.client({"Authorization": "Bearer not-a-key"}).post(
        f"{V1}/quotes", json=quote_body(), headers=KEY
    )

    for response in (by_cookie, bad_key):
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"
    assert (await session.browser.get(f"{V1}/quotes")).json() == []


async def test_an_error_of_climate_or_pricing_is_its_problem_and_stores_nothing(
    api: QuotingApi,
) -> None:
    session = await api.session()
    invalid = quote_body()
    invalid["cover"]["limit"]["amount_cents"] = 0

    invalid_cover = await session.api.post(f"{V1}/quotes", json=invalid, headers=KEY)
    api.climate.fail_with(OutsideCoverageError())
    outside = await session.api.post(
        f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": "request-2"}
    )
    api.climate.fail_with(None)

    assert (invalid_cover.status_code, invalid_cover.json()["code"]) == (422, "invalid_cover")
    assert (outside.status_code, outside.json()["code"]) == (422, "outside_coverage")
    assert (await session.browser.get(f"{V1}/quotes")).json() == []


@pytest.mark.req("R-6-5")
@pytest.mark.req("R-11.1-5")
async def test_a_submission_is_requested_once_per_quote_by_key_or_cookie(
    api: QuotingApi,
) -> None:
    session = await api.session()
    by_key = (await session.api.post(f"{V1}/quotes", json=quote_body(), headers=KEY)).json()
    by_cookie = (
        await session.api.post(
            f"{V1}/quotes", json=quote_body(), headers={"Idempotency-Key": "request-2"}
        )
    ).json()

    first = await session.api.post(
        f"{V1}/quotes/{by_key['quote_id']}/submissions", json={"carrier_id": "carrier-1"}
    )
    again = await session.browser.post(
        f"{V1}/quotes/{by_key['quote_id']}/submissions", json={"carrier_id": "carrier-2"}
    )
    human = await session.browser.post(
        f"{V1}/quotes/{by_cookie['quote_id']}/submissions", json={"carrier_id": "carrier-2"}
    )
    unknown = await session.api.post(
        f"{V1}/quotes/{by_cookie['quote_id']}/submissions", json={"carrier_id": "carrier-9"}
    )

    assert first.status_code == 200
    assert first.json()["carrier_id"] == "carrier-1"
    assert first.json()["delivery"]["status"] == "not_started"
    assert again.json() == first.json()
    assert human.json()["carrier_id"] == "carrier-2"
    assert unknown.json() == human.json()  # the quote already has its submission
    key_audit = (await session.api.get(f"{V1}/quotes/{by_key['quote_id']}")).json()["audit"]
    cookie_audit = (await session.api.get(f"{V1}/quotes/{by_cookie['quote_id']}")).json()["audit"]
    assert [(e["actor"], e["action"]["code"]) for e in key_audit] == [
        ("api_client", "audit.quote_created"),
        ("api_client", "audit.submission_requested"),
    ]
    assert key_audit[1]["action"]["params"] == {"carrier_id": "carrier-1", "key_id": "key-1"}
    assert (cookie_audit[1]["actor"], cookie_audit[1]["action"]["params"]) == (
        "human",
        {"carrier_id": "carrier-2"},
    )


async def test_an_unknown_carrier_is_refused_for_a_draft(api: QuotingApi) -> None:
    session = await api.session()
    quote = (await session.api.post(f"{V1}/quotes", json=quote_body(), headers=KEY)).json()

    response = await session.api.post(
        f"{V1}/quotes/{quote['quote_id']}/submissions", json={"carrier_id": "carrier-9"}
    )

    assert (response.status_code, response.json()["code"]) == (422, "unknown_carrier")
    assert (await session.api.get(f"{V1}/quotes/{quote['quote_id']}")).json()["status"] == "draft"
