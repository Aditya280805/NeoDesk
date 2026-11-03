"""Tests for NeoDesk User Authentication System (Phase 1)."""
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.terminal.server import create_app
from app.auth.router import _clear_rate_limits
from app.auth.service import decode_token


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Clear rate limiting attempts between tests."""
    _clear_rate_limits()
    yield
    _clear_rate_limits()


@pytest.fixture
def auth_app(tmp_path):
    """Test application configured with auth protection enabled."""
    config = Settings(
        _env_file=None,
        data_dir=tmp_path,
        environment="test",
        app_password=SecretStr("test-password-16-chars-long"),
        market_data_source="sample",
        kotak_consumer_key=None,
    )
    return create_app(config)


@pytest.fixture
def client(auth_app):
    """Test client with default NeoDesk headers."""
    with TestClient(auth_app, headers={"X-NeoDesk": "1"}) as c:
        yield c


def test_register_new_user(client, auth_app):
    """Registering a new user should return a valid JWT token and user profile."""
    payload = {
        "email": "trader@example.com",
        "password": "Password123!",
        "display_name": "Pro Trader",
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "trader@example.com"
    assert data["user"]["display_name"] == "Pro Trader"
    assert "id" in data["user"]
    assert "created_at" in data["user"]

    # Verify token decoding with app's secret
    decoded = decode_token(data["access_token"], auth_app.state.jwt_secret)
    assert decoded["email"] == "trader@example.com"
    assert decoded["user_id"] == data["user"]["id"]

    # Verify cookie was set
    assert "neodesk_token" in response.cookies


def test_register_duplicate_email(client):
    """Registering with an already registered email should fail with 400."""
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "display_name": "Trader One",
    }
    res1 = client.post("/api/auth/register", json=payload)
    assert res1.status_code == 200

    # Same email, different casing
    payload2 = {
        "email": "Duplicate@Example.com",
        "password": "Password456!",
        "display_name": "Trader Two",
    }
    res2 = client.post("/api/auth/register", json=payload2)
    assert res2.status_code == 400
    assert "already registered" in res2.json()["detail"].lower()


def test_login_valid(client):
    """Logging in with valid credentials should return a token."""
    reg_payload = {
        "email": "login_user@example.com",
        "password": "SecretPassword123!",
        "display_name": "Valid User",
    }
    reg_res = client.post("/api/auth/register", json=reg_payload)
    assert reg_res.status_code == 200

    login_payload = {
        "email": "login_user@example.com",
        "password": "SecretPassword123!",
    }
    login_res = client.post("/api/auth/login", json=login_payload)
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "login_user@example.com"
    assert "neodesk_token" in login_res.cookies


def test_login_invalid_password(client):
    """Logging in with an incorrect password should fail with 401."""
    reg_payload = {
        "email": "auth_test@example.com",
        "password": "CorrectPassword123!",
        "display_name": "Auth Tester",
    }
    client.post("/api/auth/register", json=reg_payload)

    # Wrong password
    bad_login = {
        "email": "auth_test@example.com",
        "password": "WrongPassword999!",
    }
    res = client.post("/api/auth/login", json=bad_login)
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()

    # Non-existent email
    non_existent = {
        "email": "nobody@example.com",
        "password": "SomePassword123!",
    }
    res_unknown = client.post("/api/auth/login", json=non_existent)
    assert res_unknown.status_code == 401


def test_me_authenticated(client):
    """Authenticated user can fetch their profile via Authorization header or cookie."""
    reg_payload = {
        "email": "me_user@example.com",
        "password": "Password123!",
        "display_name": "Profile Owner",
    }
    reg_res = client.post("/api/auth/register", json=reg_payload)
    token = reg_res.json()["access_token"]

    # 1. Access via Authorization Bearer header
    header_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert header_res.status_code == 200
    profile = header_res.json()
    assert profile["email"] == "me_user@example.com"
    assert profile["display_name"] == "Profile Owner"
    assert "id" in profile

    # 2. Access via cookie
    cookie_client = TestClient(client.app, cookies={"neodesk_token": token}, headers={"X-NeoDesk": "1"})
    cookie_res = cookie_client.get("/api/auth/me")
    assert cookie_res.status_code == 200
    assert cookie_res.json()["email"] == "me_user@example.com"


def test_me_unauthenticated(client):
    """Accessing /api/auth/me without token or with invalid token returns 401."""
    # No credentials
    no_token_res = client.get("/api/auth/me")
    assert no_token_res.status_code == 401

    # Invalid token
    bad_token_res = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert bad_token_res.status_code == 401


def test_protected_endpoint_without_token(client):
    """Protected endpoints should reject requests without a token and accept with valid token."""
    # Protected endpoint without token -> 401
    unauth_res = client.get("/api/paper")
    assert unauth_res.status_code == 401

    # Register to obtain token
    reg_res = client.post(
        "/api/auth/register",
        json={"email": "protected@example.com", "password": "Password123!", "display_name": "User"},
    )
    token = reg_res.json()["access_token"]

    # Access protected endpoint with valid JWT token -> 200
    auth_res = client.get("/api/paper", headers={"Authorization": f"Bearer {token}"})
    assert auth_res.status_code == 200
    assert "cash" in auth_res.json()


def test_logout(client):
    """Logging out should clear the neodesk_token cookie."""
    reg_res = client.post(
        "/api/auth/register",
        json={"email": "logout@example.com", "password": "Password123!", "display_name": "Logout User"},
    )
    assert reg_res.status_code == 200
    assert "neodesk_token" in reg_res.cookies

    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    # Cookie should be deleted/expired in response
    set_cookie = logout_res.headers.get("set-cookie", "")
    assert "neodesk_token" in set_cookie
