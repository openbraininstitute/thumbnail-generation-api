"""Typed settings, read once from the environment, one group per topic (workspace-manager pattern).

Each group is its own settings class with its own prefix, and :class:`Settings` holds them all:
``settings.entitycore.uri`` is ``ENTITY_CORE_URI``. A new topic adds one group class and one
field on :class:`Settings`.

The names the deployment already sets (infra ``thumbnail-generation-api/container.tf``) are kept
as they are, without a service prefix: ``BASE_PATH``, ``WHITELISTED_CORS_URLS``,
``CORS_ORIGIN_REGEX``, ``ENVIRONMENT``, ``SENTRY_DSN``, ``ENTITY_CORE_URI``. Renaming them would
need an infra change for no gain. The service reads no dotenv file: ``make dev`` passes
``.env`` (``uv run --env-file``), so tests see only what they are given. Every setting, with its
default and an explanation: ``.env.example`` (``tests/test_env_example.py`` keeps them in step).
"""

import re
from enum import StrEnum
from functools import lru_cache
from re import Pattern
from typing import Literal, Self

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.guards import ensure
from app.domain.types import Value

SCOPE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.]*")
LOCAL_ORIGINS = re.compile(r"http://(localhost|127[.]0[.]0[.]1)(:[0-9]+)?")
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
    """How the HTTP API is served and who may call it from a browser (no prefix: deployed names)."""

    model_config = _group("")

    base_path: str = Field(
        default="",
        pattern=r"^(/[A-Za-z0-9._~-]+)*$",
        description="Path prefix of every route: the AWS load balancer forwards "
        "{base_path}/* unstripped and checks {base_path}/health. Empty = served at /.",
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        validation_alias=AliasChoices("WHITELISTED_CORS_URLS", "cors_origins"),
        description="JSON list of browser origins allowed to call the API cross-origin.",
    )
    cors_origin_regex: Pattern[str] | None = Field(
        default=LOCAL_ORIGINS,
        description="Origins allowed by pattern, beside cors_origins (the whole origin must "
        "match). Default: http://localhost or 127.0.0.1 on any port, so a web app run locally "
        "on any port can call any deployment (bearer tokens, no cookies: such a page still "
        "needs the user's token). Empty = only the list.",
    )

    @field_validator("cors_origins")
    @classmethod
    def _origins_are_origins(cls, value: list[str]) -> list[str]:
        """Each entry is ``*`` or ``scheme://host[:port]``: they are written into nginx's config.

        A quote or a semicolon there could change nginx's configuration (api/nginx_cors.py).
        """
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
        description="Root of the entitycore API (ENTITY_CORE_URI).",
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0, description="Per request to entitycore and to the storage download."
    )
    max_connections: int = Field(
        default=32,
        ge=1,
        description="Connections one process opens to entitycore and the storage at once; more "
        "requests queue in the process. Measured on staging: 200 calls at once made entitycore "
        "answer 502/503 for minutes; without a cap a burst passes straight through.",
    )
    max_asset_bytes: int = Field(
        default=1024 * MIB,
        gt=0,
        description="Largest asset downloaded to draw. The container has 2 GB and an NWB file "
        "is held in memory while parsed; a larger asset gets ASSET_TOO_LARGE, not an OOM kill. "
        "Not measured: the size of real assets; raise it if a valid asset is refused.",
    )


class RenderSettings(BaseSettings):
    """How much drawing one process does at once (the image cache is nginx's, nginx/nginx.conf)."""

    model_config = _group("RENDER_")

    concurrency: int = Field(
        default=4,
        ge=1,
        description="Renders (CPU) one process runs at the same time; the others wait.",
    )
    downloads: int = Field(
        default=16,
        ge=1,
        description="Files one process downloads at the same time; the others wait. Also bounds "
        "the connections to entitycore and the storage.",
    )
    memory_bytes: int = Field(
        default=512 * MIB,
        ge=MIB,
        description="Memory one process may hold for the files it draws (3x each file's size). "
        "The image runs 2 processes in a 2 GiB container that idles at about 450 MiB: 2 x 512 MiB "
        "leaves room. Measured: without it, a burst of ephys files filled the 2 GiB.",
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, read from the environment on first use."""
    return Settings()
