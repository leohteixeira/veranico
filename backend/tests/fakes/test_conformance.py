"""Every fake satisfies the Protocol of its module: by type (mypy strict checks the
assignments below) and at run time (method names, parameters, annotations and `async`)."""

import inspect
from typing import get_type_hints

import pytest

from tests.fakes.access import FakeAccessFacade
from tests.fakes.assistant import FakeAssistantFacade
from tests.fakes.carriers import FakeCarrierCatalog, FakeCarriersFacade
from tests.fakes.climate import FakeClimateFacade
from tests.fakes.documents import FakeDocumentsFacade
from tests.fakes.pricing import FakePricingFacade
from tests.fakes.quoting import FakeQuotingFacade
from veranico.modules.access.contracts import AccessFacade
from veranico.modules.assistant.contracts import AssistantFacade
from veranico.modules.carriers.contracts import CarriersFacade
from veranico.modules.climate.contracts import ClimateFacade
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.pricing.contracts import PricingFacade
from veranico.modules.quoting.contracts import CarrierCatalog, QuotingFacade
from veranico.shared.infrastructure.http_auth import AccessPort

PAIRS: list[tuple[type, type]] = [
    (FakeAccessFacade, AccessFacade),
    (FakeClimateFacade, ClimateFacade),
    (FakePricingFacade, PricingFacade),
    (FakeQuotingFacade, QuotingFacade),
    (FakeCarriersFacade, CarriersFacade),
    (FakeCarrierCatalog, CarrierCatalog),
    (FakeDocumentsFacade, DocumentsFacade),
    (FakeAssistantFacade, AssistantFacade),
]


def test_fakes_are_assignable_to_their_protocols() -> None:
    quoting_fake = FakeQuotingFacade()
    access: AccessFacade = FakeAccessFacade()
    access_port: AccessPort = FakeAccessFacade()
    climate: ClimateFacade = FakeClimateFacade()
    pricing: PricingFacade = FakePricingFacade()
    quoting: QuotingFacade = quoting_fake
    carriers: CarriersFacade = FakeCarriersFacade(quoting_fake)
    catalog: CarrierCatalog = FakeCarrierCatalog()
    documents: DocumentsFacade = FakeDocumentsFacade(quoting_fake)
    assistant: AssistantFacade = FakeAssistantFacade()

    everything = [
        access,
        access_port,
        climate,
        pricing,
        quoting,
        carriers,
        catalog,
        documents,
        assistant,
    ]
    assert all(hasattr(fake, "calls") for fake in everything if fake is not catalog)


def protocol_methods(protocol: type) -> list[str]:
    return [
        name
        for name, member in vars(protocol).items()
        if inspect.isfunction(member) and not name.startswith("_")
    ]


def differences(fake: type, protocol: type) -> list[str]:
    found = []
    for name in protocol_methods(protocol):
        expected = getattr(protocol, name)
        actual = getattr(fake, name, None)
        if actual is None:
            found.append(f"{name}: missing")
            continue
        if inspect.iscoroutinefunction(actual) != inspect.iscoroutinefunction(expected):
            found.append(f"{name}: async differs")
        expected_parameters = [
            (parameter.name, parameter.kind, parameter.default)
            for parameter in inspect.signature(expected).parameters.values()
        ]
        actual_parameters = [
            (parameter.name, parameter.kind, parameter.default)
            for parameter in inspect.signature(actual).parameters.values()
        ]
        if actual_parameters != expected_parameters:
            found.append(f"{name}: parameters differ")
        if get_type_hints(actual) != get_type_hints(expected):
            found.append(f"{name}: annotations differ")
    return found


@pytest.mark.parametrize(("fake", "protocol"), PAIRS, ids=lambda cls: cls.__name__)
def test_fake_has_the_methods_of_its_protocol(fake: type, protocol: type) -> None:
    assert protocol_methods(protocol), "the Protocol declares no method"
    assert differences(fake, protocol) == []


def test_every_facade_protocol_has_a_fake() -> None:
    facades = {protocol.__name__ for _, protocol in PAIRS if protocol.__name__.endswith("Facade")}

    assert facades == {
        "AccessFacade",
        "ClimateFacade",
        "PricingFacade",
        "QuotingFacade",
        "CarriersFacade",
        "DocumentsFacade",
        "AssistantFacade",
    }


def test_the_comparison_reports_a_fake_that_drifted() -> None:
    class Drifted:
        def catalog(self, extra: int) -> None:  # a parameter the Protocol does not have
            raise NotImplementedError

        def deliver(self, event_id: str, attempt: int) -> None:  # not async
            raise NotImplementedError

    found = differences(Drifted, CarriersFacade)

    assert "catalog: parameters differ" in found
    assert "deliver: async differs" in found
    assert differences(type("Empty", (), {}), CarriersFacade) == [
        "catalog: missing",
        "deliver: missing",
    ]
