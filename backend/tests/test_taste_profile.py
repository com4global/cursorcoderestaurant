"""Tests for Taste Profile API (AI Flavor / Recommendations)."""
import pytest
from tests.conftest import (
    get_auth_header,
    register_user,
    create_test_restaurant,
    create_test_category,
    create_test_item,
)


def _user_token(client, email="taste_user@test.com"):
    resp = register_user(client, email=email)
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _owner_token(client, email="taste_owner@test.com"):
    resp = register_user(client, email=email, role="owner")
    assert resp.status_code == 200
    return resp.json()["access_token"]


class TestTasteProfileAPI:
    """GET and PUT /taste/profile."""

    def test_get_taste_profile_creates_default_if_missing(self, client):
        token = _user_token(client, "taste_get1@test.com")
        resp = client.get("/taste/profile", headers=get_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["spice_level"] == "medium"
        assert data["diet"] is None
        assert data["liked_cuisines"] == []
        assert data["disliked_tags"] is None
        assert "id" in data
        assert data["user_id"] > 0
        assert "updated_at" in data

    def test_put_taste_profile_updates_preferences(self, client):
        token = _user_token(client, "taste_put1@test.com")
        # Create profile first
        client.get("/taste/profile", headers=get_auth_header(token))
        # Update
        resp = client.put(
            "/taste/profile",
            headers=get_auth_header(token),
            json={
                "spice_level": "spicy",
                "diet": "vegetarian",
                "liked_cuisines": ["Indian", "Thai"],
                "disliked_tags": "nuts",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["spice_level"] == "spicy"
        assert data["diet"] == "vegetarian"
        assert set(data["liked_cuisines"]) == {"Indian", "Thai"}
        assert data["disliked_tags"] == "nuts"

    def test_get_after_put_returns_saved_values(self, client):
        token = _user_token(client, "taste_roundtrip@test.com")
        client.put(
            "/taste/profile",
            headers=get_auth_header(token),
            json={"spice_level": "mild", "liked_cuisines": ["Italian"]},
        )
        resp = client.get("/taste/profile", headers=get_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["spice_level"] == "mild"
        assert resp.json()["liked_cuisines"] == ["Italian"]

    def test_taste_profile_requires_auth(self, client):
        resp = client.get("/taste/profile")
        assert resp.status_code == 401
        resp = client.put("/taste/profile", json={"spice_level": "medium"})
        assert resp.status_code == 401


class TestTasteHistorySummary:
    """GET /taste/history-summary — taste vector from completed orders."""

    def test_history_summary_empty_when_no_orders(self, client):
        token = _user_token(client, "history_empty@test.com")
        resp = client.get("/taste/history-summary", headers=get_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["ordered_item_ids"] == []
        assert data["cuisine_counts"] == {}
        assert data["protein_counts"] == {}
        assert data["item_names"] == []
        assert data["total_orders"] == 0

    def test_history_summary_aggregates_completed_orders(self, client, db):
        from app import models

        customer_token = _user_token(client, "history_cust@test.com")
        owner_token = _owner_token(client, "history_owner@test.com")
        r = create_test_restaurant(client, owner_token, "History Rest")
        rid = r.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        i1 = create_test_item(client, owner_token, cid, "Chicken Biryani", 1299)
        i2_resp = client.post(
            f"/owner/categories/{cid}/items",
            headers=get_auth_header(owner_token),
            json={"name": "Paneer Tikka", "price_cents": 899, "cuisine": "Indian", "protein_type": "paneer"},
        )
        assert i2_resp.status_code in (200, 201)
        i1_id = i1.json()["id"]
        i2_id = i2_resp.json()["id"]

        user = db.query(models.User).filter(models.User.email == "history_cust@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="completed", total_cents=2198)
        db.add(order)
        db.commit()
        db.refresh(order)
        db.add(models.OrderItem(order_id=order.id, menu_item_id=i1_id, quantity=2, price_cents=1299))
        db.add(models.OrderItem(order_id=order.id, menu_item_id=i2_id, quantity=1, price_cents=899))
        db.commit()

        resp = client.get("/taste/history-summary", headers=get_auth_header(customer_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orders"] == 1
        assert len(data["ordered_item_ids"]) == 3
        assert data["ordered_item_ids"].count(i1_id) == 2
        assert data["ordered_item_ids"].count(i2_id) == 1
        assert "Chicken Biryani" in data["item_names"] or "Paneer Tikka" in data["item_names"]
        assert isinstance(data["cuisine_counts"], dict)
        assert isinstance(data["protein_counts"], dict)

    def test_history_summary_requires_auth(self, client):
        resp = client.get("/taste/history-summary")
        assert resp.status_code == 401


class TestTasteRecommendations:
    """GET /taste/recommendations — personalized picks."""

    def test_recommendations_requires_auth(self, client):
        resp = client.get("/taste/recommendations")
        assert resp.status_code == 401

    def test_recommendations_returns_list(self, client):
        token = _user_token(client, "rec_user@test.com")
        resp = client.get("/taste/recommendations", headers=get_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_recommendations_with_restaurants_return_items(self, client, db):
        from app import models

        customer_token = _user_token(client, "rec_cust2@test.com")
        owner_token = _owner_token(client, "rec_owner2@test.com")
        r = create_test_restaurant(client, owner_token, "Rec Rest")
        rid = r.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Chicken Biryani", 1299)
        create_test_item(client, owner_token, cid, "Paneer Tikka", 899)

        user = db.query(models.User).filter(models.User.email == "rec_cust2@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="completed", total_cents=1299)
        db.add(order)
        db.commit()
        db.refresh(order)
        oi = db.query(models.MenuItem).filter(models.MenuItem.category_id == cid).first()
        db.add(models.OrderItem(order_id=order.id, menu_item_id=oi.id, quantity=1, price_cents=1299))
        db.commit()

        resp = client.get("/taste/recommendations?limit=5", headers=get_auth_header(customer_token))
        assert resp.status_code == 200
        recs = resp.json()
        assert isinstance(recs, list)
        for r in recs:
            assert "menu_item_id" in r
            assert "name" in r
            assert "restaurant_name" in r
            assert "reason" in r
            assert "price_cents" in r
