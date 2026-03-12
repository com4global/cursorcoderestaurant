"""
Shared fixtures for RestaurantAI backend tests.

Uses an in-memory SQLite database so tests are fast and isolated.
"""

import os, sys

# ── Force test-friendly env BEFORE any app module is imported ────────────
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET"] = "test-secret-key-for-ci"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["LLM_ENABLED"] = "false"
os.environ["OPENAI_API_KEY"] = "sk-test-fake"
os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake"
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_test_fake"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_fake"
os.environ["STRIPE_STANDARD_PRICE_ID"] = "price_fake_std"
os.environ["STRIPE_CORPORATE_PRICE_ID"] = "price_fake_corp"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# ── Now import app modules (they read env at import time) ─────────────
from app.db import Base, get_db
from app.main import app

# ── Test DB engine ────────────────────────────────────────────────────
TEST_DB_URL = "sqlite:///./test.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()

TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once per test session."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    # Clean up test.db file
    if os.path.exists("./test.db"):
        os.remove("./test.db")
    for f in ["./test.db-shm", "./test.db-wal"]:
        if os.path.exists(f):
            os.remove(f)


@pytest.fixture()
def db():
    """Fresh DB session per test — rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSession(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    """FastAPI test client that uses the test DB session."""
    def override_get_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helper functions ──────────────────────────────────────────────────

def register_user(client, email="test@example.com", password="password123", role="customer"):
    """Register a user and return the response data."""
    endpoint = "/auth/register" if role == "customer" else "/auth/register-owner"
    resp = client.post(endpoint, json={"email": email, "password": password})
    return resp


def get_auth_header(token):
    """Build Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


def create_test_restaurant(client, token, name="Test Restaurant", city="Test City"):
    """Create a restaurant and return the response data."""
    resp = client.post(
        "/owner/restaurants",
        json={"name": name, "city": city},
        headers=get_auth_header(token),
    )
    return resp


def create_test_category(client, token, restaurant_id, name="Main Course"):
    """Create a category and return the response data."""
    resp = client.post(
        f"/owner/restaurants/{restaurant_id}/categories",
        json={"name": name},
        headers=get_auth_header(token),
    )
    return resp


def create_test_item(client, token, category_id, name="Chicken Biryani", price_cents=1499):
    """Create a menu item and return the response data."""
    resp = client.post(
        f"/owner/categories/{category_id}/items",
        json={"name": name, "price_cents": price_cents},
        headers=get_auth_header(token),
    )
    return resp
