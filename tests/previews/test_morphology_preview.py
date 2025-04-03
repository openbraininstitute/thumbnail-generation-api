from http import HTTPStatus as status
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.core.api import ApiError, ApiErrorCode
from api.exceptions import ContentEmpty


@patch("api.router.core.morphology.get_entitycore_client")
def test_morphology_preview_success(
    mock_get_entitycore_client,
    client: TestClient,
    mock_headers,
    mock_entity_id,
    mock_asset_id,
    mock_morphology_content,
):
    """Test successful morphology preview generation"""
    # Setup mock for entitycore client
    mock_client = AsyncMock()
    mock_client.get_asset_download_url = AsyncMock(return_value="http://example.com/download")
    mock_client.get_asset_content = AsyncMock(return_value=mock_morphology_content)

    # Configure the context manager
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client
    mock_context.__aexit__.return_value = None
    mock_get_entitycore_client.return_value = mock_context

    response = client.get(
        "/core/reconstruction-morphology/preview",
        headers=mock_headers,
        params={
            "entity_id": str(mock_entity_id),
            "asset_id": str(mock_asset_id),
            "dpi": 300,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@patch("api.router.core.morphology.get_entitycore_client")
def test_morphology_preview_without_dpi(
    mock_get_entitycore_client,
    client: TestClient,
    mock_headers,
    mock_entity_id,
    mock_asset_id,
    mock_morphology_content,
):
    """Test preview generation without specifying DPI (should use default)"""
    mock_client = AsyncMock()
    mock_client.get_asset_download_url = AsyncMock(return_value="http://example.com/download")
    mock_client.get_asset_content = AsyncMock(return_value=mock_morphology_content)

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client
    mock_context.__aexit__.return_value = None
    mock_get_entitycore_client.return_value = mock_context

    response = client.get(
        "/core/reconstruction-morphology/preview",
        headers=mock_headers,
        params={
            "entity_id": str(mock_entity_id),
            "asset_id": str(mock_asset_id),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@patch("api.router.core.morphology.get_entitycore_client")
def test_morphology_preview_invalid_dpi(
    mock_get_entitycore_client,
    client: TestClient,
    mock_headers,
    mock_entity_id,
    mock_asset_id,
):
    """Test preview generation with invalid DPI value"""
    response = client.get(
        "/core/reconstruction-morphology/preview",
        headers=mock_headers,
        params={
            "entity_id": str(mock_entity_id),
            "asset_id": str(mock_asset_id),
            "dpi": 5,  # Too low, should fail validation
        },
    )

    assert response.status_code == 422  # Validation error


@patch("api.router.core.morphology.get_entitycore_client")
def test_morphology_preview_asset_not_found(
    mock_get_entitycore_client,
    client: TestClient,
    mock_headers,
    mock_entity_id,
    mock_asset_id,
):
    """Test handling of non-existent asset"""
    mock_client = AsyncMock()
    mock_client.get_asset_download_url = AsyncMock(side_effect=ContentEmpty("Asset not found"))

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client
    mock_context.__aexit__.return_value = None
    mock_get_entitycore_client.return_value = mock_context

    with pytest.raises(ApiError) as exc_info:
        client.get(
            "/core/reconstruction-morphology/preview",
            headers=mock_headers,
            params={
                "entity_id": str(mock_entity_id),
                "asset_id": str(mock_asset_id),
                "dpi": 300,
            },
        )

    assert exc_info.value.http_status_code == status.NOT_FOUND
    assert exc_info.value.error_code == ApiErrorCode.ASSET_NOT_FOUND
    assert exc_info.value.message == "404: Asset not found"


def test_morphology_preview_missing_auth(
    client: TestClient,
    mock_entity_id,
    mock_asset_id,
):
    """Test that authentication is required"""
    response = client.get(
        "/core/reconstruction-morphology/preview",
        params={
            "entity_id": str(mock_entity_id),
            "asset_id": str(mock_asset_id),
            "dpi": 300,
        },
    )

    assert response.status_code == 403  # Unauthorized


def test_morphology_preview_invalid_uuid(
    client: TestClient,
    mock_headers,
):
    """Test handling of invalid UUID format"""
    response = client.get(
        "/core/reconstruction-morphology/preview",
        headers=mock_headers,
        params={
            "entity_id": "invalid-uuid",
            "asset_id": "invalid-uuid",
            "dpi": 300,
        },
    )

    assert response.status_code == 422
    response_json = response.json()
    assert "entity_id" in response_json["detail"][0]["loc"]


@patch("api.router.core.morphology.get_entitycore_client")
def test_morphology_preview_buffering_error(
    mock_get_entitycore_client,
    client: TestClient,
    mock_headers,
    mock_entity_id,
    mock_asset_id,
    mock_morphology_content,
):
    """Test handling of buffering errors during image generation"""
    mock_client = AsyncMock()
    mock_client.get_asset_download_url = AsyncMock(return_value="http://example.com/download")
    # Return valid morphology content but we'll mock the plot_morphology to fail
    mock_client.get_asset_content = AsyncMock(return_value=mock_morphology_content)

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client
    mock_context.__aexit__.return_value = None
    mock_get_entitycore_client.return_value = mock_context

    with patch("api.router.core.morphology.plot_morphology") as mock_plot:
        # Mock plot_morphology to raise an exception that will trigger a buffering error
        mock_plot.side_effect = Exception("Failed to generate buffer")
        with pytest.raises(ApiError) as exc_info:
            client.get(
                "/core/reconstruction-morphology/preview",
                headers=mock_headers,
                params={
                    "entity_id": str(mock_entity_id),
                    "asset_id": str(mock_asset_id),
                    "dpi": 300,
                },
            )

        assert exc_info.value.http_status_code == status.INTERNAL_SERVER_ERROR
        assert exc_info.value.error_code == ApiErrorCode.BUFFERING_ERROR
        assert "Error while generating the plot" in exc_info.value.message


@patch("api.router.core.morphology.get_entitycore_client")
def test_morphology_preview_too_high_dpi(
    mock_get_entitycore_client,
    client: TestClient,
    mock_headers,
    mock_entity_id,
    mock_asset_id,
):
    """Test preview generation with DPI value above maximum"""
    response = client.get(
        "/core/reconstruction-morphology/preview",
        headers=mock_headers,
        params={
            "entity_id": str(mock_entity_id),
            "asset_id": str(mock_asset_id),
            "dpi": 1000,  # Too high, should fail validation
        },
    )

    assert response.status_code == 422
    response_json = response.json()
    assert "dpi" in response_json["detail"][0]["loc"]


@patch("api.router.core.morphology.get_entitycore_client")
def test_morphology_preview_malformed_swc(
    mock_get_entitycore_client,
    client: TestClient,
    mock_headers,
    mock_entity_id,
    mock_asset_id,
):
    """Test handling of malformed SWC content"""
    mock_client = AsyncMock()
    mock_client.get_asset_download_url = AsyncMock(return_value="http://example.com/download")
    # Return malformed SWC content
    mock_client.get_asset_content = AsyncMock(return_value="malformed swc content")

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client
    mock_context.__aexit__.return_value = None
    mock_get_entitycore_client.return_value = mock_context

    with pytest.raises(ApiError) as exc_info:
        client.get(
            "/core/reconstruction-morphology/preview",
            headers=mock_headers,
            params={
                "entity_id": str(mock_entity_id),
                "asset_id": str(mock_asset_id),
                "dpi": 300,
            },
        )

    assert exc_info.value.http_status_code == status.INTERNAL_SERVER_ERROR
    assert exc_info.value.error_code == ApiErrorCode.INTERNAL_ERROR
