"""`env.example` documents exactly the variables the settings read."""

import re
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, SecretStr

from veranico.shared.infrastructure.settings import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[4] / "env.example"
ASSIGNMENT = re.compile(r"^(?:# )?([A-Z][A-Z0-9_]*)=(.*)$")


def documented() -> list[tuple[str, str]]:
    """The variables of the file, commented examples included, with their values."""
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    variables = [(match[1], match[2]) for line in lines if (match := ASSIGNMENT.match(line))]
    # Build-time variables of the frontend are documented in the same file.
    return [(name, value) for name, value in variables if not name.startswith("VITE_")]


def read_by_settings() -> dict[str, bool]:
    """Variable name -> whether the field is a secret."""
    variables: dict[str, bool] = {}
    for field_name, field in Settings.model_fields.items():
        if field.alias is not None:
            variables[field.alias] = _is_secret(field.annotation)
        elif isinstance(field.default, BaseModel):
            for nested_name, nested in type(field.default).model_fields.items():
                variable = f"VERANICO_{field_name}__{nested_name}".upper()
                variables[variable] = _is_secret(nested.annotation)
        else:
            variables[f"VERANICO_{field_name}".upper()] = _is_secret(field.annotation)
    return variables


def _is_secret(annotation: object) -> bool:
    return annotation is SecretStr or SecretStr in get_args(annotation)


def test_every_variable_is_documented_once_and_nothing_else_is() -> None:
    names = [name for name, _ in documented()]

    assert sorted(names) == sorted(set(names)), "a variable is documented twice"
    assert set(names) == set(read_by_settings())


def test_no_secret_has_a_value() -> None:
    secrets = {name for name, secret in read_by_settings().items() if secret}

    assert len(secrets) == 6  # the Earth Engine project id (ADR 0019) is not a secret
    assert {name: value for name, value in documented() if name in secrets and value} == {}
