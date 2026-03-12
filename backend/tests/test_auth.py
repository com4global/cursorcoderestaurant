"""Tests for authentication endpoints."""
import pytest
from .conftest import register_user, get_auth_header


class TestRegister:
    def test_register_customer(self, client):
        resp = client.post("/auth/register", json={
            "email": "newuser@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_register_duplicate_email(self, client):
        client.post("/auth/register", json={
            "email": "dup@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/register", json={
            "email": "dup@example.com",
            "password": "password456",
        })
        assert resp.status_code in (400, 409)

    def test_register_short_password(self, client):
        resp = client.post("/auth/register", json={
            "email": "short@example.com",
            "password": "12345",  # < 6 chars
        })
        assert resp.status_code == 422

    def test_register_invalid_email(self, client):
        resp = client.post("/auth/register", json={
            "email": "not-an-email",
            "password": "password123",
        })
        assert resp.status_code == 422


class TestLogin:
    def test_login_success(self, client):
        # Register first
        client.post("/auth/register", json={
            "email": "login@example.com",
            "password": "password123",
        })
        # Login
        resp = client.post("/auth/login", json={
            "email": "login@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_login_wrong_password(self, client):
        client.post("/auth/register", json={
            "email": "wrong@example.com",
            "password": "password123",
        })
        resp = client.post("/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code in (401, 400)

    def test_login_nonexistent_user(self, client):
        resp = client.post("/auth/login", json={
            "email": "nouser@example.com",
            "password": "password123",
        })
        assert resp.status_code in (401, 400, 404)


class TestMe:
    def test_get_me(self, client):
        resp = client.post("/auth/register", json={
            "email": "me@example.com",
            "password": "password123",
        })
        token = resp.json()["access_token"]
        resp = client.get("/auth/me", headers=get_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "me@example.com"

    def test_get_me_no_token(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code in (401, 403)

    def test_get_me_invalid_token(self, client):
        resp = client.get("/auth/me", headers=get_auth_header("invalid-token"))
        assert resp.status_code == 401
