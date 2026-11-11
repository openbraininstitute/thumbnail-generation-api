"""Which cell, protocol, repetition, sweep and response of an NWB file a preview shows.

A missing element is ``ASSET_UNREADABLE``.
"""

import re
from typing import cast

import h5py
import numpy as np

from app.domain.errors import ErrorCode
from app.domain.guards import ensure, match_error
from app.rendering.common import unreadable

PREFERRED_PROTOCOLS = ("IDRest", "APWaveform", "IDThres")
# Largest dataset decoded: HDF5 compresses, so a small file can decode to many GB.
# 256 MiB = 32M float64 samples, far above a sweep (6 MB in the fixture).
MAX_DECODED_BYTES = 256 * 1024 * 1024
RESPONSE_PREFIXES = ("ic_", "vcs_", "ccs_")


def find_digits(text: str) -> int | None:
    """The last run of digits in ``text``.

    Examples:
        >>> find_digits("sweep_12_rep3"), find_digits("none")
        (3, None)
    """
    digits = re.findall(r"([0-9]+)", text)
    return int(digits[-1]) if digits else None


def n_smallest_index(values: list[float], n: int) -> int:
    """The index of the n-th smallest value; ``n`` is clamped into range (negative from the end).

    Examples:
        >>> n_smallest_index([5, 1, 3], 0), n_smallest_index([5, 1, 3], -1)
        (1, 0)
        >>> n_smallest_index([5], 9)
        0
    """
    n = max(n, -len(values)) if n < 0 else min(n, len(values) - 1)
    return int(np.argsort(np.array(values))[n])


def select_element(names: list[str], n: int = 0, what: str = "cell") -> str:
    """The element whose trailing number is the n-th smallest (names without one sort last).

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when ``names`` is empty.

    Examples:
        >>> select_element(["sweep_3", "sweep_1", "sweep_2"], n=-3, what="sweep")
        'sweep_1'
    """
    ensure(names, lambda: unreadable(f"No {what} found in the NWB file"))
    if len(names) == 1:
        return names[0]
    digits = [find_digits(name) for name in names]
    return names[n_smallest_index([np.nan if d is None else d for d in digits], n)]


def select_protocol(protocols: list[str]) -> str:
    """The first preferred protocol present, else the first one.

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when ``protocols`` is empty.

    Examples:
        >>> select_protocol(["X", "APWaveform", "IDThres"])
        'APWaveform'
    """
    ensure(protocols, lambda: unreadable("No protocol found in the NWB file"))
    return next((p for p in PREFERRED_PROTOCOLS if p in protocols), protocols[0])


def select_response(names: list[str]) -> str:
    """The response element (not the stimulus).

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when none is a response.

    Examples:
        >>> select_response(["stim_1", "ic_1"])
        'ic_1'
    """
    found = next((n for n in names if any(p in n for p in RESPONSE_PREFIXES)), None)
    ensure(found is not None, lambda: unreadable("No response found in the NWB file"))
    return str(found)


def read_array(group: h5py.Group, name: str, dtype: type[np.floating]) -> np.ndarray:
    """``group[name]`` as an array of ``dtype``, refused before reading when it is too large.

    Raises:
        DomainError: ``ASSET_TOO_LARGE`` over :data:`MAX_DECODED_BYTES` once decoded.
    """
    dataset = cast("h5py.Dataset", group[name])
    decoded = dataset.size * np.dtype(dtype).itemsize
    ensure(
        decoded <= MAX_DECODED_BYTES,
        ErrorCode.AssetTooLarge,
        "The data in the file is too large to draw",
        limit=MAX_DECODED_BYTES,
    )
    return np.asarray(dataset, dtype=dtype)


def attribute(group: h5py.Group, dataset: str, name: str) -> object:
    """``group[dataset].attrs[name]``.

    Raises:
        DomainError: ``ASSET_UNREADABLE`` when it is missing.
    """
    try:
        return group[dataset].attrs[name]
    except KeyError as error:
        match_error(error, {KeyError: lambda _: unreadable(f"No {name} found in the NWB file")})
