"""Guard clauses (from workspace-manager): ``ensure``, ``require`` and ``match_error``.

The error is built only when a guard fails.
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
    """Map an error to an outcome with a table of handlers, tried in order.

    The first matching class wins (put a subclass before its base). A returned exception is
    raised ``from`` the original; any other result is returned. Unmatched: re-raised.

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
