"""A log line is one write: lines of several processes sharing stdout never merge."""

import io

from app.logs import configure_logging, get_logger
from app.settings import LogFormat


class Writes(io.StringIO):
    """Counts the write calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def write(self, text: str) -> int:
        self.calls.append(text)
        return super().write(text)


def test_each_line_is_one_write() -> None:
    stream = Writes()
    configure_logging(level="INFO", fmt=LogFormat.Json, stream=stream, cache=False)
    try:
        get_logger("test").info("hello", n=1)
        get_logger("test").warning("again")
    finally:
        configure_logging(level="DEBUG", fmt=LogFormat.Json, stream=io.StringIO(), cache=False)
    assert len(stream.calls) == 2
    assert all(call.endswith("}\n") and call.count("\n") == 1 for call in stream.calls)
