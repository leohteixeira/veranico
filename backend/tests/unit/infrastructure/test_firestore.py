import os

import pytest
from google.cloud.firestore import AsyncClient

from tests.fakes.settings import settings_for_tests
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client


async def test_client_targets_the_emulator_the_settings_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    settings = settings_for_tests(
        firestore_emulator_host="127.0.0.1:8580", firestore_project="veranico-test"
    )

    client = firestore_client(settings)

    assert isinstance(client, AsyncClient)
    assert client.project == "veranico-test"
    assert os.environ["FIRESTORE_EMULATOR_HOST"] == "127.0.0.1:8580"
    assert client._emulator_host == "127.0.0.1:8580"  # the SDK's own record of the target
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST")


async def test_close_is_safe_before_and_after_the_channel_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    client = firestore_client(settings_for_tests(firestore_emulator_host="127.0.0.1:8580"))

    await close_firestore(client)  # nothing was opened yet

    client.collection("access_workspaces").document("w")  # builds a reference, no I/O
    assert client._firestore_api is not None  # creates the channel lazily, still no I/O
    await close_firestore(client)
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST")
