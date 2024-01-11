# test_dependencies.py

from fastapi import HTTPException
from starlette.requests import Request
from api.user import User
from api.dependencies import retrieve_user
import jwt
import pytest

class TestRetrieveUser:
    @staticmethod
    def test_valid_token(monkeypatch):
        # Mock a valid token
        valid_token = "valid_token"
        monkeypatch.setattr(jwt, "decode", lambda token, options: {"preferred_username": "user123"})

        request = MockRequest(headers={"authorization": f"Bearer {valid_token}"})
        user = retrieve_user(request)

        assert isinstance(user, User)
        assert user.username == "user123"
        assert user.access_token == valid_token


    @staticmethod
    def test_invalid_token(monkeypatch):
        # Mock an invalid token
        invalid_token = "invalid_token"

        request = MockRequest(headers={"authorization": f"Bearer {invalid_token}"})
        with pytest.raises(HTTPException) as exc_info:
            retrieve_user(request)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Access token is invalid"

# Mock Request object for testing
class MockRequest:
    def __init__(self, headers):
        self.headers = headers
