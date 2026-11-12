"""The Firestore client shared by the modules that keep transactional state."""

import os

from google.cloud.firestore import AsyncClient

from veranico.shared.infrastructure.settings import Settings

_EMULATOR_VARIABLE = "FIRESTORE_EMULATOR_HOST"


def firestore_client(settings: Settings) -> AsyncClient:
    """Build the client: against the emulator when its host is set, otherwise with ADC.

    The SDK decides between the emulator and production only from the process environment
    (`FIRESTORE_EMULATOR_HOST`); it has no constructor argument for it. Settings are the
    single source of configuration here, so the host is exported before the client is
    built. With the variable set the SDK uses anonymous credentials and an insecure channel,
    and opens no connection until the first call.
    """
    if settings.firestore_emulator_host is not None:
        os.environ[_EMULATOR_VARIABLE] = settings.firestore_emulator_host
    return AsyncClient(project=settings.firestore_project)


async def close_firestore(client: AsyncClient) -> None:
    """Close the client's gRPC channel.

    The SDK has no public asynchronous close: the inherited `close()` only closes an HTTP
    session the asynchronous client never opens. The channel belongs to the transport of
    the generated API client, which is created on first use.
    """
    api = getattr(client, "_firestore_api_internal", None)
    if api is not None:
        await api.transport.close()
