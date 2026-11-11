"""The contract neuroagent-ts generates its types from (operation ids, parameters)."""

import json

from app.api import openapi
from app.api.problems import STATUS
from app.domain.errors import ErrorCode

# neuroagent-ts names its zod schemas after these operation ids: they must not change.
KEPT = {
    "get_morphology_preview_api_thumbnail_generation_core_cell_morphology_preview_get",
    "get_ephys_preview_api_thumbnail_generation_core_electrical_cell_recording_preview_get",
    "get_ion_channel_recording_preview_api_thumbnail_generation_core_ion_channel_recording_preview_get",
    "get_model_trace_preview_api_thumbnail_generation_core_model_trace_preview_get",
    "get_simulation_plot_api_thumbnail_generation_core__simulation_type__preview_get",
    "health_api_thumbnail_generation_health_get",
}
ASSET_QUERY = [
    ("header", "project-id"),
    ("header", "virtual-lab-id"),
    ("query", "asset_id"),
    ("query", "dpi"),
    ("query", "entity_id"),
    ("query", "format"),
]


def operations() -> dict[str, dict]:
    doc = openapi.document()
    return {op["operationId"]: op for methods in doc["paths"].values() for op in methods.values()}


def test_operation_ids_are_the_old_ones() -> None:
    assert set(operations()) == KEPT


def test_parameters_are_the_old_ones() -> None:
    ops = operations()
    for name in KEPT:
        if "_preview_get" in name and "model_trace" not in name and "simulation" not in name:
            assert sorted((p["in"], p["name"]) for p in ops[name]["parameters"]) == ASSET_QUERY


def test_committed_document_is_current() -> None:
    """Run ``make openapi`` after changing a route."""
    assert json.loads(openapi.FILE.read_text()) == json.loads(openapi.text())


def test_every_error_code_has_a_status() -> None:
    assert set(STATUS) == set(ErrorCode)


def test_preview_routes_document_images_and_problems() -> None:
    """Clients generate their error type from these answers (neuroagent-ts: ``zProblem``)."""
    problem = {"$ref": "#/components/schemas/Problem"}
    for name, op in operations().items():
        if "_preview_get" not in name:
            continue
        responses = op["responses"]
        assert set(responses["200"]["content"]) == {"image/png", "image/webp"}
        for status in {str(s) for s in STATUS.values()}:
            assert responses[status]["content"]["application/json"]["schema"] == problem
