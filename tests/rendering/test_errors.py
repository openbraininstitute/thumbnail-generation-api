"""A file that is not what a renderer reads is ASSET_UNREADABLE (422), not a crash (500)."""

import json

import pytest

from app.domain.errors import DomainError, ErrorCode
from app.domain.preview import EntityRoute, RenderSpec
from app.rendering import RENDERERS, nwb

from tests.support import DATA


@pytest.mark.parametrize(
    "route",
    [
        EntityRoute.CellMorphology,
        EntityRoute.ElectricalCellRecording,
        EntityRoute.IonChannelRecording,
        EntityRoute.SingleNeuronSimulation,
    ],
)
def test_garbage_is_unreadable(route: EntityRoute) -> None:
    with pytest.raises(DomainError) as caught:
        RENDERERS[route](b"\x00 not a file", RenderSpec(target="stimulus"))
    assert caught.value.code is ErrorCode.AssetUnreadable


def test_ion_channel_file_given_to_ephys_is_unreadable() -> None:
    with pytest.raises(DomainError) as caught:
        RENDERERS[EntityRoute.ElectricalCellRecording](
            (DATA / "ion_channel_recording.nwb").read_bytes(), RenderSpec()
        )
    assert caught.value.code is ErrorCode.AssetUnreadable


def test_simulation_without_the_target_is_plot_data_not_found() -> None:
    empty = json.dumps({"stimulus": [], "simulation": {}}).encode()
    with pytest.raises(DomainError) as caught:
        RENDERERS[EntityRoute.SingleNeuronSimulation](empty, RenderSpec(target="simulation"))
    assert caught.value.code is ErrorCode.PlotDataNotFound


def test_a_decompression_bomb_is_refused_before_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """A small compressed NWB file can hold a huge dataset: refused from its declared size."""
    monkeypatch.setattr(nwb, "MAX_DECODED_BYTES", 1024)  # the fixture's sweep is far larger
    with pytest.raises(DomainError) as caught:
        RENDERERS[EntityRoute.ElectricalCellRecording](
            (DATA / "correct_trace.nwb").read_bytes(), RenderSpec()
        )
    assert caught.value.code is ErrorCode.AssetTooLarge
