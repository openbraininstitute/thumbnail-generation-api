"""Typed guards: one way to state a rule and its error (Guard Clause pattern).

The subset of workspace-manager ``domain/guards.py`` this service uses, unchanged:

* :func:`ensure` replaces ``if not condition: raise …``.
* :func:`require` does the same for a value that must exist, and narrows ``T | None`` to ``T``.
* :func:`match_error` maps an error to an outcome with a table: one ``except`` per edge
  (spec 06 C-E5).

The error is built only when the guard fails, so the normal path allocates nothing.
"""

from collections.abc import Callable, Mapping
from typing import Any, NoReturn, overload

from app.domain.errors import DomainError, ErrorCode

type ErrorFactory = Callable[[], BaseException]
"""Builds the error to raise; called only when the check fails."""


@overload
def ensure(condition: object, error: ErrorFactory, /) -> None: ...


@overload
def ensure(condition: object, code: ErrorCode, message: str, /, **details: object) -> None: ...


def ensure(
    condition: object, error: ErrorCode | ErrorFactory, message: str = "", /, **details: object
) -> None:
    """Raise unless ``condition`` is true.

    Raises:
        DomainError: ``ensure(cond, code, message)`` when ``condition`` is falsy.
        BaseException: ``ensure(cond, lambda: SomeError())``: what the factory builds.

    Examples:
        >>> ensure(2 > 1, ErrorCode.AssetTooLarge, "never raised")
        >>> try:
        ...     ensure(0, ErrorCode.AssetTooLarge, "too large")
        ... except DomainError as error:
        ...     error.code.value
        'ASSET_TOO_LARGE'
    """
    if not condition:
        raise _built(error, message, details)


@overload
def require[T](value: T | None, error: ErrorFactory, /) -> T: ...


@overload
def require[T](value: T | None, code: ErrorCode, message: str, /, **details: object) -> T: ...


def require[T](
    value: T | None, error: ErrorCode | ErrorFactory, message: str = "", /, **details: object
) -> T:
    """``value`` when it is not None, else raise (the two forms of :func:`ensure`).

    Raises:
        DomainError: The first form, when ``value`` is None.
        BaseException: The second form: whatever the factory builds.

    Examples:
        >>> require(0, ErrorCode.AssetNotFound, "No asset")
        0
        >>> try:
        ...     require(None, ErrorCode.AssetNotFound, "No asset")
        ... except DomainError as error:
        ...     error.code.value
        'ASSET_NOT_FOUND'
    """
    if value is None:
        raise _built(error, message, details)
    return value


def _built(
    error: ErrorCode | ErrorFactory, message: str, details: dict[str, object]
) -> BaseException:
    if isinstance(error, ErrorCode):
        return DomainError(error, message, **details)
    return error()


@overload
def match_error(
    error: BaseException, handlers: Mapping[type[BaseException], Callable[[Any], BaseException]]
) -> NoReturn: ...


@overload
def match_error[R](
    error: BaseException, handlers: Mapping[type[BaseException], Callable[[Any], R]]
) -> R: ...


def match_error[R](
    error: BaseException, handlers: Mapping[type[BaseException], Callable[[Any], R]]
) -> R:
    """Map an error to an outcome with a table: one ``except`` per edge (spec 06 C-E5).

    Handlers are tried in the table's order; the first whose class matches
    (``isinstance``, so put a subclass before its base) is called with the
    error. A handler that returns an exception has it raised ``from`` the
    original; any other result is returned (await it when the handlers are
    coroutines). An error no handler matches is re-raised unchanged: nothing
    is swallowed. Handlers are functions, so only the matching one builds
    its response. When every handler returns an exception the call is typed
    ``NoReturn``, so the type checker knows the code after it is not reached.

    From workspace-manager ``domain/guards.py``, unchanged.

    Raises:
        BaseException: The handler's exception, or ``error`` itself when unmatched.

    Examples:
        >>> match_error(ValueError("x"), {ValueError: lambda e: 400, Exception: lambda e: 500})
        400
        >>> match_error(KeyError("k"), {ValueError: lambda e: 400, Exception: lambda e: 500})
        500
        >>> try:
        ...     match_error(ValueError("bad"), {
        ...         ValueError: lambda e: DomainError(ErrorCode.AssetUnreadable, str(e)),
        ...     })
        ... except DomainError as error:
        ...     error.code.value, type(error.__cause__).__name__
        ('ASSET_UNREADABLE', 'ValueError')
        >>> try:
        ...     match_error(KeyError("k"), {ValueError: lambda e: 400})
        ... except KeyError:
        ...     "re-raised"
        're-raised'
    """
    for kind, handle in handlers.items():
        if isinstance(error, kind):
            outcome = handle(error)
            if isinstance(outcome, BaseException):
                raise outcome from error
            return outcome
    raise error
