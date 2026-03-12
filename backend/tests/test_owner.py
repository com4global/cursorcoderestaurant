"""Tests for Owner Portal endpoints — restaurants, categories, menu items."""
import pytest
from .conftest import register_user, get_auth_header, create_test_restaurant, create_test_category, create_test_item


def _owner_token(client, email="owner@test.com"):
    """Register as owner and return token."""
    resp = client.post("/auth/register-owner", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestOwnerRegistration:
    def test_owner_register(self, client):
        resp = client.post("/auth/register-owner", json={
            "email": "newowner@test.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data.get("role") == "owner"

    def test_owner_login_existing(self, client):
        # Register
        client.post("/auth/register-owner", json={
            "email": "existowner@test.com",
            "password": "password123",
        })
        # Login again with same credentials
        resp = client.post("/auth/register-owner", json={
            "email": "existowner@test.com",
            "password": "password123",
        })
        assert resp.status_code == 200


class TestRestaurantCRUD:
    def test_create_restaurant(self, client):
        token = _owner_token(client, "rest_create@test.com")
        resp = create_test_restaurant(client, token, "My Restaurant", "San Francisco")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Restaurant"
        assert "id" in data
        assert "slug" in data

    def test_list_restaurants(self, client):
        token = _owner_token(client, "rest_list@test.com")
        create_test_restaurant(client, token, "Restaurant A")
        create_test_restaurant(client, token, "Restaurant B")
        resp = client.get("/owner/restaurants", headers=get_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    def test_update_restaurant(self, client):
        token = _owner_token(client, "rest_update@test.com")
        r = create_test_restaurant(client, token, "Old Name")
        rid = r.json()["id"]
        resp = client.put(
            f"/owner/restaurants/{rid}",
            json={"name": "New Name", "city": "New City"},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_create_restaurant_no_auth(self, client):
        resp = client.post("/owner/restaurants", json={"name": "Fail"})
        assert resp.status_code in (401, 403)


class TestCategoryCRUD:
    def test_create_category(self, client):
        token = _owner_token(client, "cat_create@test.com")
        r = create_test_restaurant(client, token)
        rid = r.json()["id"]
        resp = create_test_category(client, token, rid, "Appetizers")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Appetizers"

    def test_update_category(self, client):
        token = _owner_token(client, "cat_update@test.com")
        r = create_test_restaurant(client, token)
        rid = r.json()["id"]
        cat = create_test_category(client, token, rid, "Starters")
        cat_id = cat.json()["id"]
        resp = client.put(
            f"/owner/categories/{cat_id}",
            json={"name": "Updated Starters"},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200

    def test_delete_category(self, client):
        token = _owner_token(client, "cat_delete@test.com")
        r = create_test_restaurant(client, token)
        rid = r.json()["id"]
        cat = create_test_category(client, token, rid, "To Delete")
        cat_id = cat.json()["id"]
        resp = client.delete(
            f"/owner/categories/{cat_id}",
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200


class TestMenuItemCRUD:
    def test_create_item(self, client):
        token = _owner_token(client, "item_create@test.com")
        r = create_test_restaurant(client, token)
        cat = create_test_category(client, token, r.json()["id"])
        cat_id = cat.json()["id"]
        resp = create_test_item(client, token, cat_id, "Butter Chicken", 1299)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Butter Chicken"
        assert data["price_cents"] == 1299

    def test_update_item(self, client):
        token = _owner_token(client, "item_update@test.com")
        r = create_test_restaurant(client, token)
        cat = create_test_category(client, token, r.json()["id"])
        item = create_test_item(client, token, cat.json()["id"], "Old Item", 999)
        item_id = item.json()["id"]
        resp = client.put(
            f"/owner/items/{item_id}",
            json={"name": "New Item", "price_cents": 1199},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200

    def test_delete_item(self, client):
        token = _owner_token(client, "item_delete@test.com")
        r = create_test_restaurant(client, token)
        cat = create_test_category(client, token, r.json()["id"])
        item = create_test_item(client, token, cat.json()["id"], "To Delete", 500)
        item_id = item.json()["id"]
        resp = client.delete(
            f"/owner/items/{item_id}",
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200

    def test_list_categories_and_items(self, client):
        token = _owner_token(client, "item_list@test.com")
        r = create_test_restaurant(client, token)
        rid = r.json()["id"]
        cat = create_test_category(client, token, rid, "Mains")
        cat_id = cat.json()["id"]
        create_test_item(client, token, cat_id, "Item 1", 1000)
        create_test_item(client, token, cat_id, "Item 2", 2000)

        # List categories
        resp = client.get(f"/restaurants/{rid}/categories")
        assert resp.status_code == 200
        categories = resp.json()
        assert len(categories) >= 1

        # List items in category
        resp = client.get(f"/categories/{cat_id}/items")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 2
