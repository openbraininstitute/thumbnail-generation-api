"""Structured logging: one flat JSON line per event, pretty on a terminal.

Copied from workspace-manager ``logs.py`` (its choice of structlog is measured there: a JSON line
of four fields costs 4.4 µs, a call below the level 0.3 µs). Context is bound, not passed
(``bind(request_id=…)``); the standard library's records (granian, httpx2, matplotlib) go through
the same processors, so CloudWatch sees one shape.

JSON shape::

    {"timestamp":"2026-11-10T10:00:00.123456Z","level":"INFO","message":"request",
     "logger":"api.request","request_id":"…","method":"GET","path":"/core/…","status":200,
     "duration_ms":12.5,"service":"thumbnail-generation-api","component":"api","env":"production"}

Scopes (``LOG_DEBUG``): ``get_logger("http.entitycore")``; ``LOG_DEBUG=*`` makes every scope speak
at DEBUG, ``LOG_DEBUG=http,render`` only those, ``LOG_DEBUG=*,-api.request`` all but one; every
other scope keeps its warnings and errors. Unset, ``LOG_LEVEL`` rules.

Rules: a short constant ``message``, the data in fields (never an f-string), no secrets
(:data:`SECRET_KEYS` are replaced), never a query string or a presigned URL.
"""

import json
import logging
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import cache, partial
from importlib.metadata import PackageNotFoundError, version
from typing import TextIO

import structlog
from structlog.contextvars import bound_contextvars, merge_contextvars
from structlog.typing import EventDict, FilteringBoundLogger, Processor, WrappedLogger

from app.domain.guards import ensure, match_error
from app.settings import LogFormat, LogScopes, Settings

SERVICE = "thumbnail-generation-api"
REDACTED = "[redacted]"
SECRET_KEYS = frozenset(
    {"authorization", "cookie", "set-cookie", "password", "secret", "client_secret", "token"}
    | {"api_key", "email"}
)
"""Field names whose value is replaced; a name match, not a scan of the text (O(fields))."""

NOISY = (
    "httpx",
    "httpx2",
    "httpcore",
    "httpcore2",
    "urllib3",
    "asyncio",
    "matplotlib",
    "PIL",
    "kaleido",
)
"""Libraries that log a line per call at INFO; they speak only from WARNING up (their logger
and every child: SQLAlchemy and alembic set levels on the children and on ``sqlalchemy``)."""

_LEVEL_NAMES = {"exception": "ERROR", "warn": "WARNING", "fatal": "CRITICAL", "msg": "INFO"}
_HANDLER_MARK = "_thumbnail_generation"


class _NamedPrintLogger(structlog.PrintLogger):
    """A ``PrintLogger`` that knows its name and writes each line with one ``write``.

    structlog's ``print(message)`` makes two writes (the text, then the newline). nginx and two
    granian workers share the container's stdout (supervisord.conf), so another process's line
    could land between them and join two JSON objects on one line, which a log shipper cannot
    parse (found by scripts/e2e_nginx.py). One write of a line under 4 KiB is atomic on a pipe.
    """

    name = ""

    def msg(self, message: str) -> None:
        """Write ``message`` and its newline at once."""
        stream = self._file if self._file is not None else sys.stdout
        with self._lock:
            stream.write(message + "\n")
            stream.flush()

    log = debug = info = warn = warning = msg
    err = error = critical = exception = failure = fatal = msg


class _PrintFactory:
    """Builds the logger of ``get_logger(name)``: one write to ``stream`` per line."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def __call__(self, *args: object) -> _NamedPrintLogger:
        logger = _NamedPrintLogger(self._stream)
        logger.name = str(args[0]) if args else ""
        return logger


def get_logger(name: str) -> FilteringBoundLogger:
    """A logger that adds ``logger=<name>`` to its lines; use ``get_logger(__name__)``.

    Lazy: it can be created at import time, before :func:`configure_logging` ran, and takes
    the configuration on its first line. (``get_logger().bind(…)`` would not: ``bind`` on the
    lazy proxy builds a real logger on the spot, with the default processors.) The name goes
    to the logger factory, and :func:`_logger_name` writes it as the ``logger`` field.
    """
    return structlog.get_logger(name)


@contextmanager
def bind(**fields: object) -> Generator[None]:
    """Add ``fields`` to every log line logged inside the block, then take them off again.

    Blocks nest (a child workflow inside a run). Use it for what identifies the work: a run, a
    step, a request.
    """
    with bound_contextvars(**fields):
        yield


def configure_logging(
    *,
    level: str = "INFO",
    fmt: LogFormat = LogFormat.Auto,
    component: str = "api",
    environment: str = "local",
    stream: TextIO | None = None,
    cache: bool = True,
    debug: str = "",
) -> None:
    """Set up structlog and the standard library's root logger. Call once, at process start.

    Args:
        level: ``DEBUG`` … ``CRITICAL``; lines below it cost one comparison.
        fmt: ``AUTO`` writes JSON unless ``stream`` is a terminal.
        component: ``api`` or ``worker``, added to every line.
        environment: Deployment name (``prod``), added to every line.
        stream: Where lines go (stdout; a log shipper reads it). Tests pass a buffer.
        cache: Bind loggers on first use (faster). Tests turn it off so they can reconfigure.
        debug: The scopes that log at DEBUG (``LOG_DEBUG``, :class:`LogScopes`). When set it
            replaces ``level``: a selected scope logs from DEBUG, every other one only from
            WARNING, so a failure in a scope nobody selected is still seen.
    """
    stream = sys.stdout if stream is None else stream
    as_json = fmt is LogFormat.Json or (fmt is LogFormat.Auto and not stream.isatty())
    scopes = LogScopes.parse(debug)
    number = logging.DEBUG if scopes.active else logging.getLevelNamesMapping()[level.upper()]
    allowed = _scope_rule(scopes) if scopes.active else None
    shared: list[Processor] = [
        merge_contextvars,
        _logger_name,
        _level,
        structlog.processors.TimeStamper(fmt="iso" if as_json else "%H:%M:%S", utc=as_json),
        _redact,
    ]
    if as_json:  # the constant fields are for the cloud; a terminal does not need them
        shared.append(
            partial(_static, {"service": SERVICE, "component": component, "env": environment})
        )
    renderer: list[Processor] = (
        [
            structlog.processors.format_exc_info,
            structlog.processors.EventRenamer("message"),
            _lead,
            structlog.processors.JSONRenderer(
                serializer=json.dumps, default=str, separators=(",", ":"), ensure_ascii=False
            ),
        ]
        if as_json
        else [structlog.dev.ConsoleRenderer(colors=stream.isatty())]
    )
    structlog.configure(
        # With a scope selection the gate runs first: a refused line costs one lookup.
        processors=[*([_gate(allowed)] if allowed else []), *shared, *renderer],
        wrapper_class=structlog.make_filtering_bound_logger(number),
        logger_factory=_PrintFactory(stream),
        cache_logger_on_first_use=cache,
    )
    _bridge_standard_library(stream, number, shared, renderer, allowed)


def configure_from(settings: Settings, *, component: str) -> None:
    """:func:`configure_logging` with the service settings; the entry points call this.

    Does nothing when logging is already configured (tests configure it first; an app factory
    called twice in one process must not reset the loggers).
    """
    if structlog.is_configured():
        return
    configure_logging(
        debug=settings.log.debug,
        level=settings.log.level,
        fmt=settings.log.format,
        component=component,
        environment=settings.environment.value,
    )


type Allowed = Callable[[str, int], bool]
"""``(scope, level number) -> whether the line is written``."""

_LEVEL_NUMBERS = {"debug": 10, "info": 20, "msg": 20, "warn": 30, "warning": 30, "error": 40}
_LEVEL_NUMBERS |= {"exception": 40, "fatal": 50, "critical": 50}


def _scope_rule(scopes: LogScopes) -> Allowed:
    """A selected scope speaks from DEBUG, the others from WARNING; each scope is decided once."""
    selected = cache(scopes.selects)
    return lambda scope, number: number >= (logging.DEBUG if selected(scope) else logging.WARNING)


def _gate(allowed: Allowed) -> Processor:
    """Drop the lines of a scope that is not selected before any other work is done."""

    def gate(logger: WrappedLogger, method: str, event: EventDict) -> EventDict:
        ensure(
            allowed(getattr(logger, "name", ""), _LEVEL_NUMBERS.get(method, logging.INFO)),
            structlog.DropEvent,  # structlog's way to say "write nothing"
        )
        return event

    return gate


class _ScopeFilter(logging.Filter):
    """The same rule for standard library records (SQLAlchemy, httpx, granian…)."""

    def __init__(self, allowed: Allowed) -> None:
        super().__init__()
        self._allowed = allowed

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep the record when its logger's scope is selected, or it is a warning or worse."""
        return self._allowed(record.name, record.levelno)


def _bridge_standard_library(
    stream: TextIO,
    number: int,
    shared: list[Processor],
    renderer: list[Processor],
    allowed: Allowed | None,
) -> None:
    """Send ``logging`` records (granian, SQLAlchemy, httpx…) through the same processors."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderer],
        )
    )
    if allowed is not None:
        handler.addFilter(_ScopeFilter(allowed))
    setattr(handler, _HANDLER_MARK, True)
    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if not hasattr(h, _HANDLER_MARK)] + [handler]
    root.setLevel(number)
    # With a scope selection the filter decides, so a library logger must let everything pass.
    library_level = logging.NOTSET if allowed else max(number, logging.WARNING)
    for name, known in list(logging.root.manager.loggerDict.items()):
        if name.split(".")[0] in NOISY and isinstance(known, logging.Logger):
            known.setLevel(library_level)
    for name in NOISY:
        logging.getLogger(name).setLevel(library_level)


LEAD = ("timestamp", "level", "message", "logger")


def _lead(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    """JSON key order: the four fields a person reads first, then the rest (bound, then call)."""
    return {**{key: event.pop(key) for key in LEAD if key in event}, **event}


def _logger_name(logger: WrappedLogger, _: str, event: EventDict) -> EventDict:
    """``logger``: the name given to ``get_logger``, or the record's name for a library."""
    record = event.get("_record")  # set by ProcessorFormatter for a standard library record
    name = getattr(record, "name", None) or getattr(logger, "name", "")
    if name:
        event["logger"] = name
    return event


def _level(_: WrappedLogger, method: str, event: EventDict) -> EventDict:
    """``level`` as the cloud filters know it: ``INFO``, ``WARNING``, ``ERROR``."""
    event["level"] = _LEVEL_NAMES.get(method, method.upper())
    return event


def _static(fields: dict[str, str], _: WrappedLogger, __: str, event: EventDict) -> EventDict:
    for key, value in fields.items():
        event.setdefault(key, value)
    return event


def _redact(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    """C-E4: no secrets, no tokens, no addresses in a log line."""
    for key in SECRET_KEYS & event.keys():
        event[key] = REDACTED
    return event


def package_version() -> str:
    """The installed version, for the ``version`` field of the start-up line."""
    try:
        return version(SERVICE)
    except PackageNotFoundError as error:
        return match_error(error, {PackageNotFoundError: lambda _: "unknown"})
