from typing import Literal

import pytest
from pydantic import ValidationError

from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import WorkspaceId
from veranico.shared.kernel.principal import Principal


def test_principal_fields_are_the_contract() -> None:
    fields = Principal.model_fields
    assert list(fields) == ["workspace_id", "kind", "key_id"]
    assert fields["workspace_id"].annotation is WorkspaceId
    assert fields["kind"].annotation == Literal["browser", "api_key", "system"]
    assert fields["key_id"].annotation == str | None
    assert fields["key_id"].default is None


def test_principal_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        Principal.model_validate({"workspace_id": "w-1", "kind": "admin"})


def test_principal_is_frozen_and_hashable() -> None:
    principal = Principal(workspace_id=WorkspaceId("w-1"), kind="browser")

    assert principal == Principal(workspace_id=WorkspaceId("w-1"), kind="browser")
    assert len({principal, principal}) == 1
    with pytest.raises(ValidationError):
        principal.kind = "system"  # type: ignore[misc]  # the assignment is the behaviour under test


def test_coded_fields_are_the_contract() -> None:
    fields = Coded.model_fields
    assert list(fields) == ["code", "params"]
    assert fields["code"].annotation is str
    assert fields["params"].annotation == dict[str, str | int | float]
    assert fields["params"].default == {}


def test_coded_default_params_are_not_shared() -> None:
    first, second = Coded(code="audit.approved"), Coded(code="audit.rejected")

    assert first.params == {}
    assert first.params is not second.params


def test_coded_keeps_money_and_rate_parameters_as_given() -> None:
    coded = Coded(
        code="assumption.loads", params={"limit_cents": 30_000_000, "risk_rate": "0.300000"}
    )

    assert coded.model_dump(mode="json") == {
        "code": "assumption.loads",
        "params": {"limit_cents": 30_000_000, "risk_rate": "0.300000"},
    }


def test_coded_rejects_a_nested_parameter() -> None:
    with pytest.raises(ValidationError):
        Coded.model_validate({"code": "x", "params": {"nested": {"a": 1}}})
