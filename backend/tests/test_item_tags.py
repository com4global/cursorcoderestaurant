"""Tests for item tagging (taste profile / recommendations)."""
import pytest
from tests.conftest import get_auth_header, register_user, create_test_restaurant, create_test_category, create_test_item


def _owner_token(client, email="tags_owner@test.com"):
    resp = register_user(client, email=email, role="owner")
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestItemTagsDerived:
    """Tags derived from name, cuisine, protein_type when not set."""

    def test_category_items_include_derived_tags(self, client):
        token = _owner_token(client, "tags_derived@test.com")
        r = create_test_restaurant(client, token, "Tag Rest")
        rid = r.json()["id"]
        cat = create_test_category(client, token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, token, cid, "Chicken Biryani", 1299)
        resp = client.get(f"/categories/{cid}/items")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        first = next((i for i in items if "Biryani" in i["name"]), items[0])
        assert "tags" in first
        assert isinstance(first["tags"], list)
        assert "biryani" in first["tags"] or "chicken" in first["tags"]

    def test_derive_item_tags_helper(self):
        from app.taste_tags import derive_item_tags
        tags = derive_item_tags("Paneer Tikka Masala", "Indian", "paneer")
        assert "vegetarian" in tags
        assert "indian" in tags or "Indian" in tags
        tags2 = derive_item_tags("Chicken Biryani", None, None)
        assert "biryani" in tags2
        assert "chicken" in tags2


class TestItemTagsExplicit:
    """Explicit tags set by owner are returned."""

    def test_create_item_with_tags_returns_them(self, client):
        token = _owner_token(client, "tags_explicit@test.com")
        r = create_test_restaurant(client, token, "Explicit Tag Rest")
        rid = r.json()["id"]
        cat = create_test_category(client, token, rid, "Sides")
        cid = cat.json()["id"]
        resp = client.post(
            f"/owner/categories/{cid}/items",
            headers=get_auth_header(token),
            json={
                "name": "Custom Dish",
                "price_cents": 599,
                "tags": ["spicy", "custom-tag"],
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["tags"] == ["spicy", "custom-tag"]

    def test_public_category_items_shows_stored_tags(self, client):
        token = _owner_token(client, "tags_public@test.com")
        r = create_test_restaurant(client, token, "Public Tag Rest")
        rid = r.json()["id"]
        cat = create_test_category(client, token, rid, "Mains")
        cid = cat.json()["id"]
        client.post(
            f"/owner/categories/{cid}/items",
            headers=get_auth_header(token),
            json={"name": "Plain Rice", "price_cents": 299, "tags": ["rice", "mild"]},
        )
        resp = client.get(f"/categories/{cid}/items")
        assert resp.status_code == 200
        items = resp.json()
        plain = next((i for i in items if i["name"] == "Plain Rice"), None)
        assert plain is not None
        assert set(plain["tags"]) >= {"rice", "mild"}
