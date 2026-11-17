"""nginx's CORS map: the list by default; the local pattern allows every localhost port, nothing
that only looks like localhost."""

import re

import pytest

from app.api.nginx_cors import map_conf
from app.settings import ApiSettings

LOCAL = "http://(localhost|127[.]0[.]0[.]1)(:[0-9]+)?"  # the local value in .env.example


def allowed(origin: str, api: ApiSettings) -> bool:
    """The origin as nginx's map would decide, read back from the map's own lines."""
    conf = map_conf(api)
    for line in conf.splitlines():
        match = re.fullmatch(r'\s+"(.+)" \$http_origin;', line)
        if not match:
            continue
        pattern = match.group(1)
        if pattern.startswith("~"):  # nginx: a regular expression, searched in the origin
            if re.search(pattern.removeprefix("~"), origin):
                return True
        elif pattern == origin:
            return True
    return False


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://localhost:5173", "http://localhost", "http://127.0.0.1:8080"],
)
def test_the_local_pattern_allows_every_localhost_port(origin: str) -> None:
    assert allowed(origin, ApiSettings(cors_origin_regex=LOCAL))


def test_by_default_only_the_list_is_allowed() -> None:
    assert ApiSettings().cors_origin_regex is None  # production never sets it
    assert allowed("http://localhost:3000", ApiSettings())
    assert not allowed("http://localhost:5173", ApiSettings())


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:3000",  # not http
        "http://localhost.evil.test",
        "http://localhost:3000.evil.test",
        "http://evil.test/http://localhost:3000",
        "http://notlocalhost:3000",
        "http://127.0.0.1.evil.test",
        "http://127x0x0x1:3000",
    ],
)
def test_lookalikes_are_refused(origin: str) -> None:
    assert not allowed(origin, ApiSettings(cors_origin_regex=LOCAL))


def test_an_empty_pattern_allows_only_the_list() -> None:
    api = ApiSettings(cors_origin_regex="", cors_origins=["https://app.example"])
    assert allowed("https://app.example", api)
    assert not allowed("http://localhost:3000", api)
