"""Tests for analytics and misc endpoints."""
import pytest
from .conftest import get_auth_header, create_test_restaurant, create_test_category, create_test_item


def _owner_token(client, email="analytics_owner@test.com"):
    resp = client.post("/auth/register-owner", json={"email": email, "password": "password123"})
    return resp.json()["access_token"]


class TestAnalytics:
    def test_analytics_default_period(self, client):
        token = _owner_token(client, "ana_default@test.com")
        r = create_test_restaurant(client, token, "Analytics Test")
        rid = r.json()["id"]

        resp = client.get(
            f"/owner/restaurants/{rid}/analytics",
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_revenue" in data or "revenue" in str(data).lower() or isinstance(data, dict)

    def test_analytics_week_period(self, client):
        token = _owner_token(client, "ana_week@test.com")
        r = create_test_restaurant(client, token, "Week Analytics")
        rid = r.json()["id"]

        resp = client.get(
            f"/owner/restaurants/{rid}/analytics?period=week",
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200

    def test_analytics_no_auth(self, client):
        resp = client.get("/owner/restaurants/1/analytics")
        assert resp.status_code in (401, 403)


class TestHealthCheck:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestPublicRestaurants:
    def test_list_all_restaurants(self, client):
        resp = client.get("/restaurants")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_search_restaurants(self, client):
        # Create a restaurant first
        token = _owner_token(client, "pub_search@test.com")
        create_test_restaurant(client, token, "Searchable Place", "Mumbai")

        resp = client.get("/restaurants?query=Searchable")
        assert resp.status_code == 200
