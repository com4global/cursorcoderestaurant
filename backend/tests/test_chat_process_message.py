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

    def test_mixed_tamil_english_food_query_returns_restaurant_suggestions(self, client):
        token = _user_token(client, "norest_mixed_tamil@test.com")
        owner_token = _owner_token(client, "norest_mixed_tamil_owner@test.com")
        r = create_test_restaurant(client, owner_token, "Tamil Mix Kitchen")
        cat = create_test_category(client, owner_token, r.json()["id"], "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Chicken Biryani", 1099)

        resp = client.post(
            "/chat/message",
            json={"text": "எனக்கு chicken biryani வேண்டும்", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        assert "biryani" in reply.lower() or "restaurant" in reply.lower() or "found" in reply.lower()


class TestSelectedRestaurantSuggestionGuard:
    """Vague recommendation-style prompts inside a selected restaurant should browse, not mutate the cart."""

    def test_vague_spicy_option_request_returns_categories_not_added(self, client):
        token = _user_token(client, "selected_suggest1@test.com")
        owner_token = _owner_token(client, "selected_suggest1_owner@test.com")
        rest = create_test_restaurant(client, owner_token, "Suggestion Guard Rest")
        rest_id = rest.json()["id"]
        slug = rest.json()["slug"]
        mains = create_test_category(client, owner_token, rest_id, "Mains")
        create_test_category(client, owner_token, rest_id, "Today's Specials")
        create_test_item(client, owner_token, mains.json()["id"], "Spicy Chicken Lollipop", 699)

        select_resp = client.post(
            "/chat/message",
            json={"text": f"#{slug}", "session_id": None},
            headers=get_auth_header(token),
        )
        session_id = select_resp.json()["session_id"]

        resp = client.post(
            "/chat/message",
            json={"text": "I want some special spicy item today can you give me some option", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Pick a category" in data["reply"]
        assert "Added to your order" not in data["reply"]
        assert data.get("categories")
        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] == 0

    def test_recommendation_phrase_with_selected_restaurant_returns_browse_guidance(self, client):
        token = _user_token(client, "selected_suggest2@test.com")
        owner_token = _owner_token(client, "selected_suggest2_owner@test.com")
        rest = create_test_restaurant(client, owner_token, "Browse Guidance Rest")
        rest_id = rest.json()["id"]
        slug = rest.json()["slug"]
        starters = create_test_category(client, owner_token, rest_id, "Starters")
        create_test_item(client, owner_token, starters.json()["id"], "Paneer Tikka", 899)

        select_resp = client.post(
            "/chat/message",
            json={"text": f"#{slug}", "session_id": None},
            headers=get_auth_header(token),
        )
        session_id = select_resp.json()["session_id"]

        resp = client.post(
            "/chat/message",
            json={"text": "recommend something special here", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Pick a category" in data["reply"]
        assert data.get("categories")
        assert "Added to your order" not in data["reply"]

    def test_direct_order_still_adds_item_after_guard(self, client):
        token = _user_token(client, "selected_suggest3@test.com")
        owner_token = _owner_token(client, "selected_suggest3_owner@test.com")
        rest = create_test_restaurant(client, owner_token, "Direct Order Rest")
        rest_id = rest.json()["id"]
        slug = rest.json()["slug"]
        mains = create_test_category(client, owner_token, rest_id, "Mains")
        create_test_item(client, owner_token, mains.json()["id"], "Spicy Chicken Lollipop", 699)

        select_resp = client.post(
            "/chat/message",
            json={"text": f"#{slug}", "session_id": None},
            headers=get_auth_header(token),
        )
        session_id = select_resp.json()["session_id"]

        resp = client.post(
            "/chat/message",
            json={"text": "add one spicy chicken lollipop", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Added to your order" in data["reply"]
        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] > 0

    def test_explicit_global_context_clears_stale_restaurant_session(self, client):
        token = _user_token(client, "selected_suggest4@test.com")
        owner_token = _owner_token(client, "selected_suggest4_owner@test.com")
        rest = create_test_restaurant(client, owner_token, "Stale Session Rest")
        rest_id = rest.json()["id"]
        slug = rest.json()["slug"]
        specials = create_test_category(client, owner_token, rest_id, "Today's Specials")
        create_test_item(client, owner_token, specials.json()["id"], "Butter Masala", 1600)

        select_resp = client.post(
            "/chat/message",
            json={"text": f"#{slug}", "session_id": None},
            headers=get_auth_header(token),
        )
        session_id = select_resp.json()["session_id"]

        resp = client.post(
            "/chat/message",
            json={
                "text": "give me some suggestion for todays special",
                "session_id": session_id,
                "restaurant_id": None,
            },
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Added to your order" not in data["reply"]
        assert data.get("restaurant_id") is None

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] == 0


class TestMultiOrderSessionReset:
    def test_multi_order_clears_selected_restaurant_before_follow_up_browse(self, client):
        token = _user_token(client, "multi_followup1@test.com")
        owner_token = _owner_token(client, "multi_followup1_owner@test.com")

        anjappar = create_test_restaurant(client, owner_token, "Anjappar")
        aroma = create_test_restaurant(client, owner_token, "Aroma")

        soups = create_test_category(client, owner_token, anjappar.json()["id"], "Soups")
        breads = create_test_category(client, owner_token, aroma.json()["id"], "Breads")
        create_test_item(client, owner_token, soups.json()["id"], "Mutton Bone Soup", 599)
        create_test_item(client, owner_token, breads.json()["id"], "Butter Naan", 350)

        select_resp = client.post(
            "/chat/message",
            json={"text": f"#{anjappar.json()['slug']}", "session_id": None},
            headers=get_auth_header(token),
        )
        assert select_resp.status_code == 200
        session_id = select_resp.json()["session_id"]

        multi_resp = client.post(
            "/chat/message",
            json={
                "text": "1 butter naan from aroma and 1 mutton bone soup from anjappar",
                "session_id": session_id,
            },
            headers=get_auth_header(token),
        )
        assert multi_resp.status_code == 200
        assert "Added to your orders" in multi_resp.json()["reply"]
        assert multi_resp.json().get("restaurant_id") is None

        cart_before = client.get("/cart", headers=get_auth_header(token)).json()
        total_before = cart_before["grand_total_cents"]

        follow_up = client.post(
            "/chat/message",
            json={"text": "give me some suggestion for todays special", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert follow_up.status_code == 200
        data = follow_up.json()
        assert "Added to your order" not in data["reply"]
        assert data.get("restaurant_id") is None

        cart_after = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart_after["grand_total_cents"] == total_before


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

    def test_three_restaurants_voice_style_i_want_and_quantities(self, client):
        """Compound voice-style: 'i want X from A and 2 Y from B and 3 Z from C' (any combo of restaurants/menus)."""
        token = _user_token(client, "three_rest_voice@test.com")
        owner_token = _owner_token(client, "three_rest_voice_owner@test.com")

        r1 = create_test_restaurant(client, owner_token, "Aroma")
        assert r1.status_code == 200
        cat1 = create_test_category(client, owner_token, r1.json()["id"], "Biriyani")
        create_test_item(client, owner_token, cat1.json()["id"], "Chicken Biryani", 1299)

        r2 = create_test_restaurant(client, owner_token, "Desi District")
        assert r2.status_code == 200
        cat2 = create_test_category(client, owner_token, r2.json()["id"], "Beverages")
        create_test_item(client, owner_token, cat2.json()["id"], "Coke", 499)

        r3 = create_test_restaurant(client, owner_token, "Anjappar")
        assert r3.status_code == 200
        cat3 = create_test_category(client, owner_token, r3.json()["id"], "Drinks")
        create_test_item(client, owner_token, cat3.json()["id"], "Bottle of Water", 299)

        resp = client.post(
            "/chat/message",
            json={
                "text": "i want chicken biryani from aroma and 2 coke from desi district and 3 bottle of water from anjappar",
                "session_id": None,
            },
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        reply = data["reply"]
        assert "Added to your orders" in reply or "Added" in reply
        assert "Aroma" in reply
        assert "Desi District" in reply
        assert "Anjappar" in reply

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] > 0
        groups = cart.get("restaurants", [])
        restaurant_names = {g.get("restaurant_name") for g in groups if g.get("restaurant_name")}
        assert "Aroma" in restaurant_names
        assert "Desi District" in restaurant_names
        assert "Anjappar" in restaurant_names

        # Check quantities: 1 biryani, 2 coke, 3 water
        item_counts = {}
        for g in groups:
            for it in g.get("items", []):
                key = (g.get("restaurant_name"), it.get("name"))
                item_counts[key] = it.get("quantity", 0)
        assert item_counts.get(("Aroma", "Chicken Biryani")) == 1
        assert item_counts.get(("Desi District", "Coke")) == 2
        assert item_counts.get(("Anjappar", "Bottle of Water")) == 3

    def test_mixed_tamil_english_multi_restaurant_order_adds_to_both(self, client):
        token = _user_token(client, "multi_tamil_mix@test.com")
        owner_token = _owner_token(client, "multi_tamil_mix_owner@test.com")

        r1 = create_test_restaurant(client, owner_token, "Aroma")
        cat1 = create_test_category(client, owner_token, r1.json()["id"], "Mains")
        create_test_item(client, owner_token, cat1.json()["id"], "Chicken Biryani", 1299)

        r2 = create_test_restaurant(client, owner_token, "Anjappar")
        cat2 = create_test_category(client, owner_token, r2.json()["id"], "Soups")
        create_test_item(client, owner_token, cat2.json()["id"], "Mutton Soup", 699)

        resp = client.post(
            "/chat/message",
            json={
                "text": "எனக்கு 1 chicken biryani from Aroma and 1 mutton soup from Anjappar வேண்டும்",
                "session_id": None,
            },
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        assert "Added to your orders" in reply
        assert "Aroma" in reply
        assert "Anjappar" in reply

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        groups = cart.get("restaurants", [])
        restaurant_names = {g.get("restaurant_name") for g in groups if g.get("restaurant_name")}
        assert "Aroma" in restaurant_names
        assert "Anjappar" in restaurant_names

    def test_selected_restaurant_mixed_tamil_order_uses_normalized_multi_order(self, client, monkeypatch):
        token = _user_token(client, "multi_tamil_selected@test.com")
        owner_token = _owner_token(client, "multi_tamil_selected_owner@test.com")

        r1 = create_test_restaurant(client, owner_token, "Anjappar")
        slug1 = r1.json()["slug"]
        cat1 = create_test_category(client, owner_token, r1.json()["id"], "Soups")
        create_test_item(client, owner_token, cat1.json()["id"], "Mutton Bone Soup", 599)

        r2 = create_test_restaurant(client, owner_token, "Desi District")
        cat2 = create_test_category(client, owner_token, r2.json()["id"], "Breads")
        create_test_item(client, owner_token, cat2.json()["id"], "Butter Naan", 299)

        from app import chat as chat_module

        monkeypatch.setattr(
            chat_module,
            "_normalize_mixed_voice_order_text",
            lambda text, current_restaurant_name=None: "1 mutton bone soup from Anjappar and 1 butter naan from Desi District",
        )

        select_resp = client.post(
            "/chat/message",
            json={"text": f"#{slug1}", "session_id": None},
            headers=get_auth_header(token),
        )
        assert select_resp.status_code == 200
        session_id = select_resp.json()["session_id"]

        resp = client.post(
            "/chat/message",
            json={
                "text": "எனக்கு ஒரு மட்டன் bone soup அப்புறம் ஒரு butter on திஸ் டிஸ்ட்ரிக்ட்",
                "session_id": session_id,
            },
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        assert "Added to your orders" in reply
        assert "Anjappar" in reply
        assert "Desi District" in reply
        assert "Mutton Bone Soup" in reply
        assert "Butter Naan" in reply

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        groups = cart.get("restaurants", [])
        restaurant_names = {g.get("restaurant_name") for g in groups if g.get("restaurant_name")}
        assert "Anjappar" in restaurant_names
        assert "Desi District" in restaurant_names


class TestSameRestaurantMultiItemOrder:
    """User orders multiple items from same restaurant in one message, no restaurant pre-selected."""

    def test_two_items_same_restaurant_from_home_screen(self, client):
        """'1 Biryani and 1 Soup' with no restaurant selected — both items from same restaurant added."""
        token = _user_token(client, "same_rest_multi@test.com")
        owner_token = _owner_token(client, "same_rest_multi_owner@test.com")

        r = create_test_restaurant(client, owner_token, "Spice Palace")
        rid = r.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Chicken Biryani", 1299)
        create_test_item(client, owner_token, cat.json()["id"], "Mutton Soup", 599)

        resp = client.post(
            "/chat/message",
            json={"text": "1 Chicken Biryani and 1 Mutton Soup", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        reply = data["reply"]
        assert "Added" in reply
        assert "Chicken Biryani" in reply
        assert "Mutton Soup" in reply
        assert data["restaurant_id"] == rid

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] == 1299 + 599
        groups = cart.get("restaurants", [])
        assert len(groups) == 1
        assert groups[0]["restaurant_name"] == "Spice Palace"
        item_names = {it["name"] for it in groups[0].get("items", [])}
        assert "Chicken Biryani" in item_names
        assert "Mutton Soup" in item_names

    def test_two_items_same_restaurant_with_quantities(self, client):
        """'2 Biryani and 3 Soup' — correct quantities added."""
        token = _user_token(client, "same_rest_qty@test.com")
        owner_token = _owner_token(client, "same_rest_qty_owner@test.com")

        r = create_test_restaurant(client, owner_token, "Qty Palace")
        rid = r.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Naan", 199)
        create_test_item(client, owner_token, cat.json()["id"], "Dal", 299)

        resp = client.post(
            "/chat/message",
            json={"text": "2 Naan and 3 Dal", "session_id": None},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "Added" in data["reply"]
        assert data["restaurant_id"] == rid

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] == (199 * 2) + (299 * 3)

    def test_two_items_already_inside_restaurant_both_added(self, client):
        """When already inside a restaurant, ordering '1 X and 1 Y' adds both items."""
        token = _user_token(client, "inrest_multi@test.com")
        owner_token = _owner_token(client, "inrest_multi_owner@test.com")

        r = create_test_restaurant(client, owner_token, "Inside Rest")
        rid = r.json()["id"]
        slug = r.json()["slug"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        create_test_item(client, owner_token, cat.json()["id"], "Paneer Tikka", 899)
        create_test_item(client, owner_token, cat.json()["id"], "Garlic Naan", 299)

        # Navigate into the restaurant first
        r1 = client.post(
            "/chat/message",
            json={"text": f"#{slug}", "session_id": None},
            headers=get_auth_header(token),
        )
        assert r1.status_code == 200
        session_id = r1.json()["session_id"]

        # Now order both items in one message
        resp = client.post(
            "/chat/message",
            json={"text": "1 Paneer Tikka and 1 Garlic Naan", "session_id": session_id},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        reply = data["reply"]
        assert "Paneer Tikka" in reply
        assert "Garlic Naan" in reply
        assert data["restaurant_id"] == rid

        cart = client.get("/cart", headers=get_auth_header(token)).json()
        assert cart["grand_total_cents"] == 899 + 299
