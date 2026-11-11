"""The base of every value object."""

from pydantic import BaseModel, ConfigDict


class Value(BaseModel):
    """A frozen value object, compared by value; fields are validated when it is made.

    Examples:
        >>> class Point(Value):
        ...     x: int
        >>> Point(x=1) == Point(x=1)
        True
    """

    # forbid: a misspelled field fails instead of being dropped.
    model_config = ConfigDict(frozen=True, extra="forbid")
