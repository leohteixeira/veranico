"""Write the OpenAPI document of the API role to `backend/openapi.json`.

    uv run python scripts/export_openapi.py            # write the file
    uv run python scripts/export_openapi.py --check    # exit 1 when the file is out of date

The application is built with fixed placeholder settings and is never started, so the
export needs no network, no emulator and no credential, and gives the same bytes on every
machine. The frontend client is generated from this file.
"""

import argparse
import json
import sys
from pathlib import Path

from veranico.main import create_app
from veranico.shared.infrastructure.settings import Settings

OUTPUT = Path(__file__).resolve().parent.parent / "openapi.json"


def export_settings() -> Settings:
    """Settings that let the API role be built. None of the values is used or a secret."""
    return Settings(
        app_role="api",
        environment="development",
        # Naming an emulator keeps the Firestore client from looking for credentials. The
        # client connects on first use, and nothing here uses it.
        firestore_emulator_host="127.0.0.1:8580",
        cookie_signing_secret="openapi-export-placeholder",
        access={"ip_hash_salt": "openapi-export-placeholder"},
        delivery={
            "webhook_signing_secret": "openapi-export-placeholder",
            "internal_auth": "disabled",
        },
        assistant={"model_client": "scripted"},
    )


def render() -> str:
    document = create_app(export_settings()).openapi()
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="compare with the file on disk; write nothing"
    )
    arguments = parser.parse_args()
    rendered = render()
    if not arguments.check:
        OUTPUT.write_text(rendered, encoding="utf-8")
        print(f"wrote {OUTPUT.name}")
        return 0
    if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
        print(
            f"{OUTPUT.name} is out of date: run `make gen-client` and commit the result",
            file=sys.stderr,
        )
        return 1
    print(f"{OUTPUT.name} is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
