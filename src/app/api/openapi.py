"""Writes the committed ``openapi.json`` (``make openapi``), with the deployed base path.

``tests/api/test_openapi.py`` fails when the file and the code differ.
"""

import json
from pathlib import Path
from typing import Any

from app.api.app import create_app
from app.settings import ApiSettings, Settings

DEPLOYED_BASE_PATH = "/api/thumbnail-generation"
FILE = Path("openapi.json")


def document() -> dict[str, Any]:
    """The OpenAPI document of the app served under the deployed base path."""
    return create_app(Settings(api=ApiSettings(base_path=DEPLOYED_BASE_PATH))).openapi()


def text() -> str:
    """The document as it is written to the file."""
    return json.dumps(document(), indent=2) + "\n"


if __name__ == "__main__":
    FILE.write_text(text())
