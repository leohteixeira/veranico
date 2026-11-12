"""Shared set-up of the climate integration tests."""

import pytest

# `store_contract.py` holds test methods but is not a test module, so pytest would not
# rewrite its asserts (and would not explain a failure) without this.
pytest.register_assert_rewrite("tests.integration.climate.store_contract")
