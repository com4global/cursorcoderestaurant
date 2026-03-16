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


class TestGroupOrderIntent:
    """Group order intent returns open_group_tab and Group Order message."""

    def test_group_order_phrase_returns_open_group_tab(self, client):
        token = _user_token(client, "group_intent1@test.com")
        resp = client.post(
            "/chat/message",
            json={"text": "I want to start a group order", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("open_group_tab") is True
        assert "group order" in data["reply"].lower() or "Group Order" in data["reply"]

    def test_find_food_for_n_people_returns_open_group_tab(self, client):
        token = _user_token(client, "group_intent2@test.com")
        resp = client.post(
            "/chat/message",
            json={"text": "Find food for 4 people", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("open_group_tab") is True
        assert "group" in data["reply"].lower()

    def test_office_lunch_returns_open_group_tab(self, client):
        token = _user_token(client, "group_intent3@test.com")
        resp = client.post(
            "/chat/message",
            json={"text": "We need office lunch for the team", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("open_group_tab") is True

    def test_regular_message_does_not_return_open_group_tab(self, client):
        token = _user_token(client, "group_intent4@test.com")
        resp = client.post(
            "/chat/message",
            json={"text": "I want biryani", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("open_group_tab") is not True


class TestNoRestaurantFoodSearch:
    """User on Chat with no restaurant selected: food queries return cross-restaurant results or options."""

    def test_spicy_biryani_returns_found_at_restaurants_or_options(self, client):
        token = _user_token(client, "norest_biryani@test.com")
        owner_token = _owner_token(client, "norest_biryani_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Biryani House")
        cat = create_test_category(client, owner_token, r.json()["id"], "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Spicy Chicken Biryani", 1299)

        resp = client.post(
            "/chat/message",
            json={"text": "I want some spicy biryani with best value", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        reply = data["reply"]
        # Should get cross-restaurant result or "Found" listing, not "pick a restaurant first"
        assert "Found" in reply or "Biryani" in reply or "biryani" in reply or "restaurant" in reply.lower()
        assert "pick a restaurant first" not in reply

    def test_cheap_biryani_returns_results_or_restaurant_list(self, client):
        token = _user_token(client, "norest_cheap@test.com")
        owner_token = _owner_token(client, "norest_cheap_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Value Kitchen")
        cat = create_test_category(client, owner_token, r.json()["id"], "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Chicken Biryani", 899)

        resp = client.post(
            "/chat/message",
            json={"text": "cheap biryani", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        assert "Found" in reply or "Biryani" in reply or "biryani" in reply or "restaurant" in reply.lower() or "Available" in reply

    def test_best_combos_relaxed_search_returns_something(self, client):
        token = _user_token(client, "norest_combos@test.com")
        owner_token = _owner_token(client, "norest_combos_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Combo Place")
        cat = create_test_category(client, owner_token, r.json()["id"], "Combos")
        create_test_item(client, owner_token, cat.json()["id"], "Family Combo", 1999)

        resp = client.post(
            "/chat/message",
            json={"text": "give me options like best combos", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        # Relaxed search or fallback: should not be "couldn't find that restaurant" without listing options
        assert "Combo" in reply or "combo" in reply or "restaurant" in reply.lower() or "Available" in reply or "options" in reply.lower()


class TestMultiRestaurantOrder:
    """User orders from multiple restaurants in one message: '2 X from A and 1 Y from B'."""

    def test_two_restaurants_one_message_adds_to_both_orders(self, client):
        token = _user_token(client, "multi_order@test.com")
        owner_token = _owner_token(client, "multi_order_owner@test.com")

        r1 = create_test_restaurant(client, owner_token, "Aroma")
        assert r1.status_code == 200
        aroma_id = r1.json()["id"]
        cat1 = create_test_category(client, owner_token, aroma_id, "Mains")
        create_test_item(client, owner_token, cat1.json()["id"], "Chicken Biryani", 1299)

        r2 = create_test_restaurant(client, owner_token, "Desi District")
        assert r2.status_code == 200
        desi_id = r2.json()["id"]
        cat2 = create_test_category(client, owner_token, desi_id, "Starters")
        create_test_item(client, owner_token, cat2.json()["id"], "Chicken Lollipop", 699)

        resp = client.post(
            "/chat/message",
            json={
                "text": "I would like to order 2 chicken biryani from Aroma and 1 chicken lollipop from Desi District",
                "session_id": None,
            },
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        reply = data["reply"]
        assert "Added to your orders" in reply
        assert "Aroma" in reply
        assert "Desi District" in reply
        assert "Chicken Biryani" in reply or "biryani" in reply.lower()
        assert "Chicken Lollipop" in reply or "lollipop" in reply.lower()
        assert "2" in reply
        assert "1" in reply

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] > 0
        groups = cart.get("restaurants", [])
        restaurant_names = {g.get("restaurant_name") for g in groups if g.get("restaurant_name")}
        assert len(groups) >= 2, "Cart should have orders from both Aroma and Desi District"
        assert "Aroma" in restaurant_names
        assert "Desi District" in restaurant_names

    def test_multi_restaurant_reply_has_cart_summary(self, client):
        token = _user_token(client, "multi_cart@test.com")
        owner_token = _owner_token(client, "multi_cart_owner@test.com")

        r1 = create_test_restaurant(client, owner_token, "Pizza Hub")
        cat1 = create_test_category(client, owner_token, r1.json()["id"], "Pizza")
        create_test_item(client, owner_token, cat1.json()["id"], "Margherita", 999)

        r2 = create_test_restaurant(client, owner_token, "Burger Spot")
        cat2 = create_test_category(client, owner_token, r2.json()["id"], "Burgers")
        create_test_item(client, owner_token, cat2.json()["id"], "Cheese Burger", 599)

        resp = client.post(
            "/chat/message",
            json={
                "text": "1 margherita from Pizza Hub and 1 cheese burger from Burger Spot",
                "session_id": None,
            },
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("cart_summary") is not None
        assert "Added to your orders" in data["reply"] or "Pizza Hub" in data["reply"]
        assert data["restaurant_id"] is None  # multi-restaurant keeps no single selection
