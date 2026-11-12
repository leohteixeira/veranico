"""Failure tests of `assistant`: the real module over HTTP on the Firestore emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/failure/assistant -q

The application is the one of the API tests (`tests/api/assistant/conftest.py`): the module
built by `module.build`, the neighbour modules as fakes, the model scripted.
"""

from collections.abc import AsyncIterator

import pytest

from tests.api.assistant.conftest import AssistantApi, build_api


@pytest.fixture
async def api() -> AsyncIterator[AssistantApi]:
    context = build_api()
    yield context
    await context.close()
