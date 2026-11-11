""".env.example lists every setting, in the order of settings.py, with the value the app uses."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from app.settings import ApiSettings, Settings

ENV_EXAMPLE = Path(__file__).parent.parent / ".env.example"
OUTSIDE_SETTINGS = ["MPLCONFIGDIR", "API_PORT", "CACHE_UI_PORT", "IMAGE"]  # read by others


def written() -> dict[str, str]:
    lines = ENV_EXAMPLE.read_text().splitlines()
    pairs = [line.split("=", 1) for line in lines if line and not line.startswith("#")]
    return dict(pairs)


def names(model: type[BaseSettings]) -> list[str]:
    """Every environment variable of the settings, in declaration order."""
    found: list[str] = []
    prefix = str(model.model_config.get("env_prefix", ""))
    for name, field in model.model_fields.items():
        kind = field.annotation
        if isinstance(kind, type) and issubclass(kind, BaseSettings):
            found += names(kind)
            continue
        alias = field.validation_alias
        choices = getattr(alias, "choices", None)
        found.append(str(choices[0] if choices else alias or f"{prefix}{name}").upper())
    return found


def test_every_setting_is_written_in_order() -> None:
    assert list(written()) == names(Settings) + OUTSIDE_SETTINGS


def test_the_written_values_are_the_defaults() -> None:
    values = written()
    defaults = Settings()  # no environment in tests: every group takes its defaults
    assert values["ENVIRONMENT"] == defaults.environment.value
    assert values["ENTITY_CORE_URI"] == defaults.entitycore.uri
    assert int(values["ENTITY_CORE_MAX_ASSET_BYTES"]) == defaults.entitycore.max_asset_bytes
    assert float(values["ENTITY_CORE_TIMEOUT_SECONDS"]) == defaults.entitycore.timeout_seconds
    assert int(values["RENDER_CONCURRENCY"]) == defaults.render.concurrency
    assert float(values["SENTRY_TRACES_SAMPLE_RATE"]) == defaults.sentry.traces_sample_rate
    assert float(values["SENTRY_PROFILES_SAMPLE_RATE"]) == defaults.sentry.profiles_sample_rate
    assert values["LOG_LEVEL"] == defaults.log.level
    assert values["LOG_FORMAT"] == defaults.log.format.value
    assert defaults.api.cors_origin_regex is not None
    assert values["CORS_ORIGIN_REGEX"] == defaults.api.cors_origin_regex.pattern
    assert values["WHITELISTED_CORS_URLS"] == '["http://localhost:3000"]'
    assert defaults.api.cors_origins == ["http://localhost:3000"]


def test_every_variable_has_an_explanation_above_it() -> None:
    lines = ENV_EXAMPLE.read_text().splitlines()
    for index, line in enumerate(lines):
        if line and not line.startswith("#"):
            assert lines[index - 1].startswith("# "), f"no explanation above {line}"


def test_cors_values_that_could_change_nginx_config_are_refused() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(cors_origins=['http://a.test" $x; #'])
    with pytest.raises(ValidationError):
        ApiSettings(cors_origin_regex='http://a"')
    assert ApiSettings(cors_origins=["*", "http://localhost:3000"]).cors_origins
