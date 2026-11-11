"""The language of a download (plan 05, decision 11): `?lang=`, `Accept-Language`, then `en`."""

import pytest

from veranico.modules.documents.http.router import document_locale
from veranico.shared.kernel.ids import Locale


@pytest.mark.parametrize(
    ("lang", "accept_language", "expected"),
    [
        ("pt-BR", None, "pt-BR"),
        ("en", "pt-BR,pt;q=0.9", "en"),  # the query parameter wins
        (None, "pt-BR,pt;q=0.9,en;q=0.8", "pt-BR"),
        (None, "pt", "pt-BR"),
        (None, "pt-PT", "pt-BR"),
        (None, "PT-br", "pt-BR"),
        (None, "en-US,en;q=0.9", "en"),
        (None, "en", "en"),
        (None, "es-AR, es;q=0.9, pt;q=0.5, en;q=0.4", "pt-BR"),  # first supported, in order
        (None, "fr-FR, de;q=0.8", "en"),
        (None, "*", "en"),
        (None, "ptx, enx", "en"),  # only the primary subtag counts
        (None, " , ;q=1", "en"),
        (None, "", "en"),
        (None, None, "en"),
    ],
)
def test_the_language_of_a_download(
    lang: Locale | None, accept_language: str | None, expected: Locale
) -> None:
    assert document_locale(lang, accept_language) == expected
