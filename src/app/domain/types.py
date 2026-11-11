"""The base of every value object (from workspace-manager ``domain/types.py``)."""

from pydantic import BaseModel, ConfigDict


class Value(BaseModel):
    """Base of every value object in the service: frozen, compared by value (Value Object).

    One class style everywhere instead of ``@dataclass(frozen=True)``. Keyword arguments
    only; construction validates the fields, so a wrong type fails where the value is made.
    A field holding a non-Pydantic object (a numpy array) needs ``arbitrary_types_allowed``.

    Examples:
        >>> class Point(Value):
        ...     x: int
        >>> Point(x=1) == Point(x=1)
        True
    """

    # forbid: a misspelled keyword (``Value(dpii=5)``) fails here instead of being dropped.
    model_config = ConfigDict(frozen=True, extra="forbid")
