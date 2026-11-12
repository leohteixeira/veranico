import pytest

from veranico.modules.carriers.domain.directory import CARRIERS, CarrierDirectory
from veranico.modules.quoting.contracts import CarrierCatalog, CarrierInfo

pytestmark = pytest.mark.req("R-7-12")

BASE_URL = "http://carrier.test:8510"


def test_directory_satisfies_the_catalog_port_of_quoting() -> None:
    catalog: CarrierCatalog = CarrierDirectory(BASE_URL)

    assert all(isinstance(carrier, CarrierInfo) for carrier in catalog.all())


def test_directory_is_a_fixed_list_of_at_least_two_carriers() -> None:
    directory = CarrierDirectory(BASE_URL)

    first = directory.all()
    first.clear()  # a caller's copy: changing it must not change the directory

    assert len(directory.all()) >= 2
    assert directory.all() == directory.all()
    assert directory.all() == CarrierDirectory("http://elsewhere.test").all()


def test_carrier_ids_are_unique() -> None:
    ids = [carrier.carrier_id for carrier in CarrierDirectory(BASE_URL).all()]

    assert len(ids) == len(set(ids))


def test_get_returns_the_listed_carrier() -> None:
    directory = CarrierDirectory(BASE_URL)

    for carrier in directory.all():
        assert directory.get(carrier.carrier_id) == carrier


def test_get_of_an_unknown_id_returns_none() -> None:
    assert CarrierDirectory(BASE_URL).get("no-such-carrier") is None


def test_carrier_info_exposes_id_and_name_only() -> None:
    carrier = CarrierDirectory(BASE_URL).all()[0]

    assert set(carrier.model_dump()) == {"carrier_id", "name"}
    assert carrier.name


def test_webhook_url_joins_the_base_url_and_the_carrier_path() -> None:
    entry = CARRIERS[0]

    url = CarrierDirectory(BASE_URL).webhook_url(entry.carrier_id)

    assert url == BASE_URL + entry.webhook_path
    assert entry.webhook_path == "/carrier/v1/submissions"


def test_webhook_url_tolerates_a_trailing_slash_in_the_base_url() -> None:
    entry = CARRIERS[0]

    url = CarrierDirectory(BASE_URL + "/").webhook_url(entry.carrier_id)

    assert url == BASE_URL + entry.webhook_path


def test_webhook_url_of_an_unknown_id_is_none() -> None:
    assert CarrierDirectory(BASE_URL).webhook_url("no-such-carrier") is None
