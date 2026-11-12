import pytest

from veranico.shared.kernel import errors
from veranico.shared.kernel.errors import DomainError

# contracts.md section 1 (codes) and plan 00 decision 4 (statuses): code -> (status, retryable).
# `unauthorized` and `internal_error` came with the pre-deploy campaign of 2026-11-11 (F-004,
# F-002): a missing or invalid API key, and an unexpected failure answered as a problem.
EXPECTED: dict[str, tuple[int, bool]] = {
    "not_found": (404, False),
    "location_not_found": (404, False),
    "dataset_not_found": (404, False),
    "unauthorized": (401, False),
    "forbidden": (403, False),
    "conflict": (409, False),
    "invalid_state": (409, False),
    "idempotency_conflict": (409, False),
    "invalid_arguments": (422, False),
    "invalid_cover": (422, False),
    "insufficient_history": (422, False),
    "outside_coverage": (422, False),
    "unknown_carrier": (422, False),
    "message_too_long": (422, False),
    "location_ambiguous": (422, False),
    "rate_limited": (429, False),
    "allowance_exhausted": (429, False),
    "spend_ceiling_reached": (429, False),
    "delivery_failed": (502, False),
    "weather_source_unavailable": (503, True),
    "model_unavailable": (503, True),
    "shutting_down": (503, True),
    "not_implemented": (501, False),
    "internal_error": (500, False),
}


def _classes() -> list[type[DomainError]]:
    return [
        value
        for value in vars(errors).values()
        if isinstance(value, type) and issubclass(value, DomainError) and value is not DomainError
    ]


def test_every_code_has_exactly_one_class() -> None:
    codes = [cls.code for cls in _classes()]

    assert sorted(codes) == sorted(EXPECTED)
    assert len(codes) == len(set(codes))


def test_every_class_is_a_direct_subclass_defined_in_the_kernel() -> None:
    assert set(_classes()) == set(DomainError.__subclasses__())


@pytest.mark.parametrize("cls", _classes(), ids=lambda cls: cls.code)
def test_status_and_retryable_follow_the_decision_table(cls: type[DomainError]) -> None:
    status, retryable = EXPECTED[cls.code]

    assert cls.status == status
    assert cls.retryable is retryable


def test_base_class_is_not_retryable_by_default() -> None:
    assert DomainError.retryable is False


def test_an_error_carries_its_code_and_an_optional_detail() -> None:
    plain = errors.NotFoundError()
    detailed = errors.InvalidCoverError("exit must be below the trigger")

    assert isinstance(plain, Exception)
    assert (plain.code, plain.detail, str(plain)) == ("not_found", None, "not_found")
    assert detailed.detail == "exit must be below the trigger"
    assert str(detailed) == "exit must be below the trigger"
