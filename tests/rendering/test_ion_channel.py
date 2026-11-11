"""The vectorised artifact smoothing gives the old loops' results bit for bit.

The reference below is the old code, unchanged.
"""

import statistics

import numpy as np
import pytest

from app.rendering import ion_channel


def old_compute_derivatives(array: np.ndarray) -> list[np.float32]:
    derivatives = []
    count = len(array)
    for i in range(count):
        before = max(0, i - 1)
        after = min(count - 1, i + 1)
        deriv_before = array[i] - array[before]
        deriv_after = array[after] - array[i]
        value = max(abs(deriv_before), abs(deriv_after))
        derivatives.append(value)
    return derivatives


def old_remove_artifacts(data: np.ndarray, index: int) -> np.ndarray:
    array = data[:, index]
    suspiscion = 2
    for _loops in range(3):
        derivatives = old_compute_derivatives(array)
        mean_derivative = statistics.mean(derivatives)  # ty: ignore[invalid-argument-type]
        threshold = mean_derivative * suspiscion
        suspiscious_indexes = [i for i in range(len(array)) if derivatives[i] > threshold]
        if len(suspiscious_indexes) == 0:
            return array
        ion_channel.remove_suspicious_indexes(array, suspiscious_indexes)
    return array


def recording(seed: int, samples: int, traces: int, scale: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    data = rng.normal(0, 1, (samples, traces)).cumsum(axis=0) * scale
    spikes = rng.integers(0, samples, size=max(1, samples // 200))
    data[spikes, :] += 50 * scale  # artifacts to smooth
    return data.astype(np.float32)


@pytest.mark.parametrize(
    ("seed", "samples", "traces", "scale"),
    [(1, 2, 1, 1.0), (2, 50, 3, 1e-12), (3, 1200, 6, 1.0), (4, 5000, 4, 1e3), (5, 20000, 2, 1e-9)],
)
def test_same_smoothing_as_the_old_loops(
    seed: int, samples: int, traces: int, scale: float
) -> None:
    old, new = recording(seed, samples, traces, scale), recording(seed, samples, traces, scale)
    for trace in range(traces):
        old_remove_artifacts(old, trace)
        ion_channel.remove_artifacts(new, trace)
    assert old.tobytes() == new.tobytes()


@pytest.mark.parametrize("seed", range(20))
def test_exact_mean_is_statistics_mean(seed: int) -> None:
    rng = np.random.default_rng(seed)
    values = (rng.random(1000) * 10.0 ** rng.integers(-30, 30, 1000)).astype(np.float32)
    values[rng.integers(0, 1000, 10)] = 0
    expected = statistics.mean(list(values))  # ty: ignore[invalid-argument-type]
    got = ion_channel.exact_mean(values)
    assert isinstance(expected, np.float32)  # statistics keeps the items' type
    assert type(got) is np.float32
    assert got.tobytes() == expected.tobytes()


def test_derivatives_are_the_old_ones() -> None:
    array = recording(7, 3000, 1, 1.0)[:, 0]
    old = np.array(old_compute_derivatives(array), dtype=np.float32)
    assert old.tobytes() == ion_channel.compute_derivatives(array).tobytes()
