"""Quiet, structured logs for every test, and a writable matplotlib cache."""

import io
import os
import tempfile

import pytest

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl-"))

from app.logs import configure_logging
from app.settings import LogFormat


@pytest.fixture(scope="session", autouse=True)
def _logging() -> None:
    """JSON into a buffer (nothing on the terminal), unbound loggers so a test can capture."""
    configure_logging(level="DEBUG", fmt=LogFormat.Json, stream=io.StringIO(), cache=False)
