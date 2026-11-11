"""Typed settings from the environment, one group per topic.

``settings.entitycore.uri`` is ``ENTITY_CORE_URI``; deployed names keep no prefix (``BASE_PATH``,
``SENTRY_DSN``...). No dotenv file is read. Every setting is explained in ``.env.example``.
"""

import re
from enum import StrEnum
from functools import lru_cache
from re import Pattern
from typing import Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.application.admission import MEMORY_FACTOR
from app.domain.guards import ensure
from app.domain.types import Value

SCOPE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.]*")
ORIGIN = re.compile(r"\*|https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?")
MIB = 1024 * 1024


class Environment(StrEnum):
    """Where the service runs; added to every log line and to Sentry events."""

    Local = "local"
    Development = "development"
    Staging = "staging"
    Production = "production"


class LogFormat(StrEnum):
    """How a log line is written (``app.logs``)."""

    Auto = "AUTO"  # JSON, except on a terminal
    Json = "JSON"
    Console = "CONSOLE"


class LogScopes(Value):
    """Which log scopes speak at DEBUG (``LOG_DEBUG``, like the ``debug`` library).

    Examples:
        >>> scopes = LogScopes.parse("*,-api.request")
        >>> scopes.selects("http.entitycore"), scopes.selects("api.request")
        (True, False)
        >>> LogScopes.parse("").active
        False
    """

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read ``a,b`` / ``*`` / ``*,-c``; commas or spaces separate; ``a.*`` means ``a``.

        Raises:
            ValueError: A name with a character a scope cannot have.
        """
        include: list[str] = []
        exclude: list[str] = []
        for raw in text.replace(",", " ").split():
            name = raw.removeprefix("-").removesuffix(".*")
            ok = name == "*" or SCOPE_NAME.fullmatch(name)
            ensure(ok, lambda raw=raw: ValueError(f"not a log scope: {raw!r}"))
            (exclude if raw.startswith("-") else include).append(name)
        return cls(include=tuple(include), exclude=tuple(exclude))

    @property
    def active(self) -> bool:
        """Whether anything is selected (when not, the plain ``LOG_LEVEL`` applies)."""
        return bool(self.include)

    def selects(self, scope: str) -> bool:
        """Whether ``scope`` speaks at DEBUG: selected, and not taken out."""
        return any(_covers(p, scope) for p in self.include) and not any(
            _covers(p, scope) for p in self.exclude
        )


def _covers(pattern: str, scope: str) -> bool:
    return pattern in {"*", scope} or scope.startswith(pattern + ".")


def _group(prefix: str) -> SettingsConfigDict:
    """The config of every group: its prefix, the process environment only, no unknown field."""
    return SettingsConfigDict(env_prefix=prefix, extra="forbid", populate_by_name=True)


class ApiSettings(BaseSettings):
    """How the API is served and which browser origins may call it."""

    model_config = _group("")

    base_path: str = Field(
        default="",
        pattern=r"^(/[A-Za-z0-9._~-]+)*$",
        description="Path prefix of every route (the load balancer does not strip it).",
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        validation_alias=AliasChoices("WHITELISTED_CORS_URLS", "cors_origins"),
        description="JSON list of browser origins allowed to call the API cross-origin.",
    )
    cors_origin_regex: Pattern[str] | None = Field(
        default=None,
        description="Origins allowed by a pattern matching the whole origin; default: none.",
    )

    @field_validator("cors_origins")
    @classmethod
    def _origins_are_origins(cls, value: list[str]) -> list[str]:
        """Each entry is ``*`` or ``scheme://host[:port]``: it is written into nginx's config."""
        for origin in value:
            ensure(
                ORIGIN.fullmatch(origin),
                lambda origin=origin: ValueError(f"not an origin: {origin!r}"),
            )
        return value

    @field_validator("cors_origin_regex", mode="after")
    @classmethod
    def _pattern_is_safe_for_nginx(cls, value: Pattern[str] | None) -> Pattern[str] | None:
        """No quote and no control character: the pattern is written into nginx's config."""
        unsafe = value is not None and any(c == '"' or not c.isprintable() for c in value.pattern)
        ensure(
            not unsafe, lambda: ValueError("CORS_ORIGIN_REGEX has a quote or a control character")
        )
        return value

    @field_validator("cors_origin_regex", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        """Compose passes an unset variable as ``""``, which is not a pattern."""
        return None if value == "" else value


class EntitycoreSettings(BaseSettings):
    """The entitycore service that owns the assets and decides who may read them."""

    model_config = _group("ENTITY_CORE_")

    uri: str = Field(
        default="https://staging.openbraininstitute.org/api/entitycore",
        description="Root of the entitycore API.",
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0, description="Per step (connect, read, write) of a call to entitycore."
    )
    download_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Whole download of one file; below nginx's proxy_read_timeout (120 s).",
    )
    max_connections: int = Field(
        default=32,
        ge=1,
        description="Connections per process to entitycore and storage (200 overloaded staging).",
    )
    max_asset_bytes: int | None = Field(
        default=None,
        gt=0,
        description="Largest asset drawn (ASSET_TOO_LARGE above); default and maximum: "
        "RENDER_MEMORY_BYTES / 3, what one drawing of it needs.",
    )

    @field_validator("max_asset_bytes", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        """Compose passes an unset variable as ``""``."""
        return None if value == "" else value


class RenderSettings(BaseSettings):
    """How much drawing one process does at once."""

    model_config = _group("RENDER_")

    concurrency: int = Field(
        default=4,
        ge=1,
        description="Renders one process runs at once; the others wait.",
    )
    downloads: int = Field(
        default=16,
        ge=1,
        description="Files one process downloads at once; the others wait.",
    )
    memory_bytes: int = Field(
        default=512 * MIB,
        ge=MIB,
        description="Memory per process for files being drawn (3x each file's size).",
    )


class SentrySettings(BaseSettings):
    """Error reporting; off when no DSN is set."""

    model_config = _group("SENTRY_")

    dsn: str = ""
    traces_sample_rate: float = Field(default=0.2, ge=0, le=1)
    profiles_sample_rate: float = Field(default=0.05, ge=0, le=1)


class LogSettings(BaseSettings):
    """What is logged and how (``LOG_``)."""

    model_config = _group("LOG_")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: LogFormat = LogFormat.Auto
    debug: str = Field(
        default="",
        description="Scopes that log at DEBUG: '*' everything, 'http.entitycore' one scope.",
    )

    @field_validator("debug")
    @classmethod
    def _scopes_are_names(cls, value: str) -> str:
        """Refuse a misspelt ``LOG_DEBUG`` at start-up."""
        LogScopes.parse(value)
        return value


class Settings(BaseSettings):
    """Service settings: one field per group, each group read with its own prefix."""

    model_config = SettingsConfigDict(extra="forbid")

    environment: Environment = Environment.Local
    api: ApiSettings = Field(default_factory=ApiSettings)
    entitycore: EntitycoreSettings = Field(default_factory=EntitycoreSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    sentry: SentrySettings = Field(default_factory=SentrySettings)
    log: LogSettings = Field(default_factory=LogSettings)

    @model_validator(mode="after")
    def _largest_asset_fits_the_budget(self) -> Self:
        """A drawing needs 3x its file: a larger limit would let one drawing OOM the container."""
        limit = self.entitycore.max_asset_bytes
        fits = limit is None or limit * MEMORY_FACTOR <= self.render.memory_bytes
        ensure(
            fits,
            lambda: ValueError(
                "ENTITY_CORE_MAX_ASSET_BYTES x 3 is over RENDER_MEMORY_BYTES; lower it or leave it "
                "empty"
            ),
        )
        return self

    @property
    def max_asset_bytes(self) -> int:
        """The largest asset drawn: the set limit, else what the memory budget allows."""
        return self.entitycore.max_asset_bytes or self.render.memory_bytes // MEMORY_FACTOR


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, read from the environment on first use."""
    return Settings()
