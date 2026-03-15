"""Tests for Group Ordering: create session, join, recommendation, split."""
import pytest
from .conftest import (
    register_user,
    get_auth_header,
    create_test_restaurant,
    create_test_category,
    create_test_item,
)


def _setup_restaurant_with_menu(client):
    """Owner + restaurant + category + items. Returns (owner_token, restaurant_id, [item_ids])."""
    resp = client.post(
        "/auth/register-owner",
        json={"email": f"group_owner_{id(client)}@test.com", "password": "password123"},
    )
    owner_token = resp.json()["access_token"]
    r = create_test_restaurant(client, owner_token, "Group Test Restaurant", "Test City")
    rid = r.json()["id"]
    cat = create_test_category(client, owner_token, rid, "Mains")
    cat_id = cat.json()["id"]
    item1 = create_test_item(client, owner_token, cat_id, "Chicken Biryani", 1499)
    item2 = create_test_item(client, owner_token, cat_id, "Paneer Biryani", 1299)
    item3 = create_test_item(client, owner_token, cat_id, "Veg Samosa", 599)
    return owner_token, rid, [item1.json()["id"], item2.json()["id"], item3.json()["id"]]


class TestGroupSessionCreateAndGet:
    def test_create_group_session_unauthenticated(self, client):
        resp = client.post("/group/session", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "share_code" in data
        assert "id" in data
        assert data["status"] == "active"
        assert data["members"] == []

    def test_create_group_session_with_zipcode(self, client):
        resp = client.post("/group/session", json={"delivery_zipcode": "94102"})
        assert resp.status_code == 200
        assert resp.json()["delivery_address_zipcode"] == "94102"

    def test_create_group_session_authenticated(self, client):
        register_user(client, "group_creator@test.com")
        token = client.post("/auth/login", json={"email": "group_creator@test.com", "password": "password123"}).json()["access_token"]
        resp = client.post("/group/session", json={}, headers=get_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["share_code"]

    def test_get_group_by_id(self, client):
        create_resp = client.post("/group/session", json={})
        gid = create_resp.json()["id"]
        resp = client.get(f"/group/{gid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == gid
        assert resp.json()["share_code"]

    def test_get_group_by_share_code(self, client):
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        resp = client.get(f"/group/{share_code}")
        assert resp.status_code == 200
        assert resp.json()["share_code"] == share_code

    def test_get_group_not_found(self, client):
        resp = client.get("/group/99999")
        assert resp.status_code == 404
        resp2 = client.get("/group/NOSUCHCODE")
        assert resp2.status_code == 404


class TestGroupJoin:
    def test_join_group_adds_member(self, client):
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        join_resp = client.post(
            f"/group/{share_code}/join",
            json={
                "name": "Alex",
                "preference": "biryani",
                "budget_cents": 1500,
                "dietary_restrictions": None,
            },
        )
        assert join_resp.status_code == 200
        assert join_resp.json()["name"] == "Alex"
        assert join_resp.json()["preference"] == "biryani"
        assert join_resp.json()["budget_cents"] == 1500

        get_resp = client.get(f"/group/{share_code}")
        assert len(get_resp.json()["members"]) == 1
        assert get_resp.json()["members"][0]["name"] == "Alex"

    def test_join_group_multiple_members(self, client):
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        for name, pref, budget in [("Alex", "biryani", 1500), ("Sam", "veg", 1200), ("Priya", "spicy", 1800)]:
            resp = client.post(
                f"/group/{share_code}/join",
                json={"name": name, "preference": pref, "budget_cents": budget, "dietary_restrictions": None},
            )
            assert resp.status_code == 200
        get_resp = client.get(f"/group/{share_code}")
        assert len(get_resp.json()["members"]) == 3

    def test_join_group_not_found(self, client):
        resp = client.post(
            "/group/99999/join",
            json={"name": "Alex", "preference": "biryani", "budget_cents": 1500},
        )
        assert resp.status_code == 404


class TestGroupRecommendation:
    def test_recommendation_requires_members(self, client):
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        resp = client.get(f"/group/{share_code}/recommendation")
        assert resp.status_code == 400  # no members

    def test_recommendation_returns_restaurant_and_dishes(self, client):
        _setup_restaurant_with_menu(client)
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Alex", "preference": "biryani", "budget_cents": 2000, "dietary_restrictions": None},
        )
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Sam", "preference": "veg", "budget_cents": 1500, "dietary_restrictions": "vegetarian"},
        )
        resp = client.get(f"/group/{share_code}/recommendation")
        assert resp.status_code == 200
        data = resp.json()
        assert "restaurant_id" in data
        assert "restaurant_name" in data
        assert "suggested_items" in data
        assert len(data["suggested_items"]) >= 1
        assert "total_cents" in data
        assert "estimated_per_person_cents" in data
        assert "reasons" in data

    def test_recommendation_group_not_found(self, client):
        resp = client.get("/group/99999/recommendation")
        assert resp.status_code == 404


class TestGroupSplit:
    def test_split_equal_no_members_fails(self, client):
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        resp = client.get(f"/group/{share_code}/split?total_cents=5000&delivery_cents=500&tax_cents=400&mode=equal")
        assert resp.status_code == 400

    def test_split_equal(self, client):
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        for name in ["Alex", "Sam", "Priya"]:
            client.post(f"/group/{share_code}/join", json={"name": name, "preference": None, "budget_cents": None, "dietary_restrictions": None})
        resp = client.get(f"/group/{share_code}/split?total_cents=4800&delivery_cents=600&tax_cents=400&mode=equal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["split_mode"] == "equal"
        assert data["total_cents"] == 4800
        assert data["delivery_cents"] == 600
        assert data["tax_cents"] == 400
        assert len(data["members"]) == 3
        total_split = sum(m["amount_cents"] for m in data["members"])
        assert total_split == 4800 + 600 + 400

    def test_split_item_based(self, client):
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        client.post(f"/group/{share_code}/join", json={"name": "Alex", "preference": None, "budget_cents": None, "dietary_restrictions": None})
        client.post(f"/group/{share_code}/join", json={"name": "Sam", "preference": None, "budget_cents": None, "dietary_restrictions": None})
        resp = client.post(
            f"/group/{share_code}/split",
            json={
                "total_cents": 3000,
                "delivery_cents": 600,
                "tax_cents": 300,
                "mode": "item",
                "member_item_cents": [
                    {"member_name": "Alex", "item_total_cents": 1800},
                    {"member_name": "Sam", "item_total_cents": 1200},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["split_mode"] == "item"
        assert len(data["members"]) == 2
        total = sum(m["amount_cents"] for m in data["members"])
        assert total == 3000 + 600 + 300


class TestGroupFullFlowAndCombinations:
    """Full flow: start group → join members (various inputs) → AI recommendation → split → add to cart."""

    def test_full_flow_create_join_recommendation_split(self, client):
        """Start group, join 2 members with all inputs, get recommendation, get split."""
        _setup_restaurant_with_menu(client)
        create_resp = client.post("/group/session", json={})
        assert create_resp.status_code == 200
        share_code = create_resp.json()["share_code"]

        client.post(
            f"/group/{share_code}/join",
            json={
                "name": "Anitha",
                "preference": "biryani",
                "budget_cents": 5000,
                "dietary_restrictions": None,
            },
        )
        client.post(
            f"/group/{share_code}/join",
            json={
                "name": "Yash",
                "preference": "veg",
                "budget_cents": 1500,
                "dietary_restrictions": "vegetarian",
            },
        )

        get_resp = client.get(f"/group/{share_code}")
        assert get_resp.status_code == 200
        assert len(get_resp.json()["members"]) == 2

        rec_resp = client.get(f"/group/{share_code}/recommendation")
        assert rec_resp.status_code == 200
        rec = rec_resp.json()
        assert rec["restaurant_id"]
        assert rec["restaurant_name"]
        assert len(rec["suggested_items"]) >= 1
        assert rec["total_cents"] > 0
        assert rec["estimated_per_person_cents"] > 0
        assert len(rec["reasons"]) >= 1

        split_resp = client.get(
            f"/group/{share_code}/split",
            params={"total_cents": rec["total_cents"], "delivery_cents": 600, "tax_cents": 400, "mode": "equal"},
        )
        assert split_resp.status_code == 200
        split = split_resp.json()
        assert len(split["members"]) == 2
        assert sum(m["amount_cents"] for m in split["members"]) == rec["total_cents"] + 600 + 400

    def test_full_flow_with_restaurant_ids_filter(self, client):
        """Create group, join members, get recommendation restricted to specific restaurant(s)."""
        owner_token, rid, item_ids = _setup_restaurant_with_menu(client)
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Alex", "preference": "biryani", "budget_cents": 2000, "dietary_restrictions": None},
        )

        rec_resp = client.get(f"/group/{share_code}/recommendation", params={"restaurant_ids": str(rid)})
        assert rec_resp.status_code == 200
        rec = rec_resp.json()
        assert rec["restaurant_id"] == rid
        assert rec["restaurant_name"] == "Group Test Restaurant"

    def test_full_flow_with_cuisine_filter(self, client):
        """Get recommendation with cuisine filter (restaurants that have matching cuisine on items)."""
        owner_token, rid, item_ids = _setup_restaurant_with_menu(client)
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Sam", "preference": "biryani", "budget_cents": 3000, "dietary_restrictions": None},
        )

        rec_resp = client.get(f"/group/{share_code}/recommendation", params={"cuisine": "Indian"})
        if rec_resp.status_code == 200:
            rec = rec_resp.json()
            assert rec["restaurant_id"] and rec["suggested_items"]
        else:
            assert rec_resp.status_code == 404

    def test_full_flow_multi_restaurant_filter(self, client):
        """Two restaurants in DB; filter by both; recommendation should be one of them."""
        owner_token, rid, _ = _setup_restaurant_with_menu(client)
        r2 = create_test_restaurant(client, owner_token, "Second Group Rest", "City2")
        rid2 = r2.json()["id"]
        cat2 = create_test_category(client, owner_token, rid2, "Mains")
        create_test_item(client, owner_token, cat2.json()["id"], "Biryani Bowl", 1299)

        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Jill", "preference": "biryani", "budget_cents": 2000, "dietary_restrictions": None},
        )

        rec_resp = client.get(f"/group/{share_code}/recommendation", params={"restaurant_ids": f"{rid},{rid2}"})
        assert rec_resp.status_code == 200
        rec = rec_resp.json()
        assert rec["restaurant_id"] in (rid, rid2)
        assert len(rec["suggested_items"]) >= 1

    def test_full_flow_recommendation_then_add_to_cart(self, client):
        """Full flow: create group, join, get recommendation, then as logged-in user add suggested items to cart."""
        _setup_restaurant_with_menu(client)
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Alex", "preference": "biryani", "budget_cents": 2000, "dietary_restrictions": None},
        )
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Sam", "preference": "veg", "budget_cents": 1500, "dietary_restrictions": "vegetarian"},
        )

        rec_resp = client.get(f"/group/{share_code}/recommendation")
        assert rec_resp.status_code == 200
        rec = rec_resp.json()

        register_user(client, "group_order_customer@test.com")
        token = client.post(
            "/auth/login",
            json={"email": "group_order_customer@test.com", "password": "password123"},
        ).json()["access_token"]

        items_payload = [{"item_id": it["item_id"], "quantity": it["quantity"]} for it in rec["suggested_items"]]
        cart_resp = client.post(
            "/cart/add-combo",
            json={"restaurant_id": rec["restaurant_id"], "items": items_payload},
            headers=get_auth_header(token),
        )
        assert cart_resp.status_code == 200
        cart = cart_resp.json()
        assert cart["grand_total_cents"] >= rec["total_cents"]
        assert len(cart["restaurants"]) >= 1
        assert any(g["restaurant_id"] == rec["restaurant_id"] for g in cart["restaurants"])

    def test_join_with_minimal_input_then_recommendation(self, client):
        """Join with only name (no preference/budget); still get recommendation."""
        _setup_restaurant_with_menu(client)
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        client.post(
            f"/group/{share_code}/join",
            json={"name": "Minimal", "preference": None, "budget_cents": None, "dietary_restrictions": None},
        )

        rec_resp = client.get(f"/group/{share_code}/recommendation")
        assert rec_resp.status_code == 200
        rec = rec_resp.json()
        assert rec["restaurant_id"] and len(rec["suggested_items"]) >= 1

    def test_three_members_different_preferences_split(self, client):
        """Three members with different preferences; recommendation and equal split."""
        _setup_restaurant_with_menu(client)
        create_resp = client.post("/group/session", json={})
        share_code = create_resp.json()["share_code"]
        for name, pref, budget in [("A", "biryani", 2000), ("B", "veg", 1500), ("C", "spicy", 1800)]:
            client.post(
                f"/group/{share_code}/join",
                json={"name": name, "preference": pref, "budget_cents": budget, "dietary_restrictions": None},
            )

        rec_resp = client.get(f"/group/{share_code}/recommendation")
        assert rec_resp.status_code == 200
        rec = rec_resp.json()
        split_resp = client.get(
            f"/group/{share_code}/split",
            params={"total_cents": rec["total_cents"], "delivery_cents": 500, "tax_cents": 300, "mode": "equal"},
        )
        assert split_resp.status_code == 200
        split = split_resp.json()
        assert len(split["members"]) == 3
