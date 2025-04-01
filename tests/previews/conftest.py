import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from tests.utils import load_content


@pytest.fixture
def mock_headers():
    """
    Mock headers fixture for dummy requests
    """
    return {
        "Authorization": "Bearer fake-super-secret-token",
    }


@pytest.fixture
def mock_entity_id():
    """
    Mock entity ID fixture for testing
    """
    return uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def mock_asset_id():
    """
    Mock asset ID fixture for testing
    """
    return uuid.UUID("87654321-4321-8765-4321-876543210987")


@pytest.fixture
def mock_morphology_content():
    """
    Mock morphology content fixture for testing
    """
    content = load_content("./tests/fixtures/data/morphology.swc")
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    return content


@pytest.fixture(scope="function")
def client():
    client = TestClient(app)
    return client
