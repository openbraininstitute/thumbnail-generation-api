from dataclasses import dataclass

from numpy.typing import NDArray


@dataclass
class IonChannelRecordingData:
    """Container for ion_channel_recording data."""

    activation_current: NDArray
    activation_dt: NDArray
