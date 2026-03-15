"""Tests for process_message behaviors: clear cart, clarification words, reset."""
import pytest
from .conftest import get_auth_header, create_test_restaurant, create_test_category, create_test_item


def _owner_token(client, email="chatpm_owner@test.com"):
    resp = client.post("/auth/register-owner", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _user_token(client, email="chatpm_user@test.com"):
    resp = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _select_restaurant_and_add_item(client, token, slug, category_id, item_name="Biryani"):
    """Select restaurant via #slug then add one item via process_message. Returns session_id."""
    r1 = client.post(
        "/chat/message",
        json={"text": f"#{slug}", "session_id": None},
        headers=get_auth_header(token),
    )
    assert r1.status_code == 200
    session_id = r1.json()["session_id"]
    r2 = client.post(
        "/chat/message",
        json={"text": item_name, "session_id": session_id},
        headers=get_auth_header(token),
    )
    assert r2.status_code == 200
    return session_id


class TestClearCartViaChat:
    """Clear cart / order fresh via process_message."""

    def test_clear_the_cart_clears_cart_and_returns_message(self, client):
        token = _user_token(client, "clear1@test.com")
        owner_token = _owner_token(client, "clear1_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Clear Cart Rest")
        rid = r.json()["id"]
        slug = r.json()["slug"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Biryani", 1299)

        session_id = _select_restaurant_and_add_item(client, token, slug, cat.json()["id"], "Biryani")
        cart_before = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart_before["grand_total_cents"] > 0

        resp = client.post(
            "/chat/message",
            json={"text": "clear the cart", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Cart cleared" in data["reply"]
        assert data.get("cart_summary") is not None
        assert data["cart_summary"]["grand_total_cents"] == 0

        cart_after = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart_after["grand_total_cents"] == 0

    def test_clear_the_court_completely_voice_clears_cart(self, client):
        """Voice often transcribes 'cart' as 'court'."""
        token = _user_token(client, "clear2@test.com")
        owner_token = _owner_token(client, "clear2_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Voice Clear Rest")
        slug = r.json()["slug"]
        cat = create_test_category(client, owner_token, r.json()["id"], "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Naan", 299)

        session_id = _select_restaurant_and_add_item(client, token, slug, cat.json()["id"], "Naan")

        resp = client.post(
            "/chat/message",
            json={"text": "clear the court completely", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        assert "Cart cleared" in resp.json()["reply"]
        assert resp.json()["cart_summary"]["grand_total_cents"] == 0

    def test_order_fresh_clears_cart(self, client):
        token = _user_token(client, "fresh1@test.com")
        owner_token = _owner_token(client, "fresh1_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Fresh Rest")
        slug = r.json()["slug"]
        cat = create_test_category(client, owner_token, r.json()["id"], "Sides")
        create_test_item(client, owner_token, cat.json()["id"], "Fries", 399)

        session_id = _select_restaurant_and_add_item(client, token, slug, cat.json()["id"], "Fries")

        resp = client.post(
            "/chat/message",
            json={"text": "order fresh", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        assert "Cart cleared" in resp.json()["reply"]


class TestClarificationWordWhat:
    """Short words like 'what' should get helpful prompt, not item search."""

    def test_what_returns_clarification_not_item_search(self, client):
        token = _user_token(client, "what1@test.com")
        owner_token = _owner_token(client, "what1_owner@test.com")
        r = create_test_restaurant(client, owner_token, "What Test Rest")
        slug = r.json()["slug"]
        cat = create_test_category(client, owner_token, r.json()["id"], "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Kulcha", 199)

        r1 = client.post(
            "/chat/message",
            json={"text": f"#{slug}", "session_id": None},
            headers=get_auth_header(token),
        )
        session_id = r1.json()["session_id"]

        resp = client.post(
            "/chat/message",
            json={"text": "what", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        # Should NOT suggest an item like "Did you mean: Kulcha?"
        assert "Did you mean" not in reply
        # Should suggest saying category, item, or done
        assert "category" in reply.lower() or "done" in reply.lower() or "order" in reply.lower()


class TestResetStartOver:
    """Reset / start over clears session and cart."""

    def test_start_over_clears_cart(self, client):
        token = _user_token(client, "reset1@test.com")
        owner_token = _owner_token(client, "reset1_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Reset Rest")
        slug = r.json()["slug"]
        cat = create_test_category(client, owner_token, r.json()["id"], "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Rice", 599)

        session_id = _select_restaurant_and_add_item(client, token, slug, cat.json()["id"], "Rice")

        resp = client.post(
            "/chat/message",
            json={"text": "start over", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        assert "reset" in resp.json()["reply"].lower() or "pick a restaurant" in resp.json()["reply"].lower()
        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] == 0
