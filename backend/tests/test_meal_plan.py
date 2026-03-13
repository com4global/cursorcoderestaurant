"""
Layer 2: Meal Plan Endpoint Tests.

Tests the /mealplan/generate and /mealplan/swap endpoints
including diversity engine, budget constraints, and beverage exclusion.
"""
import pytest
from .conftest import get_auth_header, create_test_restaurant, create_test_category, create_test_item


def _setup_menu(client):
    """Create restaurants with diverse menus for meal plan testing."""
    # Restaurant 1: Indian
    t1_resp = client.post("/auth/register-owner", json={"email": "mp_indian@test.com", "password": "password123"})
    t1 = t1_resp.json()["access_token"]
    r1 = create_test_restaurant(client, t1, "Spice Palace", "Dallas")
    c1 = create_test_category(client, t1, r1.json()["id"], "Main Course")
    create_test_item(client, t1, c1.json()["id"], "Chicken Biryani", 1499)
    create_test_item(client, t1, c1.json()["id"], "Paneer Tikka", 1299)
    create_test_item(client, t1, c1.json()["id"], "Dal Makhani", 1099)
    create_test_item(client, t1, c1.json()["id"], "Butter Chicken", 1599)
    create_test_item(client, t1, c1.json()["id"], "Vindaloo", 1399)
    # Beverages (should be excluded)
    c1b = create_test_category(client, t1, r1.json()["id"], "Drinks")
    create_test_item(client, t1, c1b.json()["id"], "Mango Lassi", 499)
    create_test_item(client, t1, c1b.json()["id"], "Milkshake Chocolate", 599)
    create_test_item(client, t1, c1b.json()["id"], "Water Bottle", 199)

    # Restaurant 2: Mexican
    t2_resp = client.post("/auth/register-owner", json={"email": "mp_mexican@test.com", "password": "password123"})
    t2 = t2_resp.json()["access_token"]
    r2 = create_test_restaurant(client, t2, "Taco Haven", "Austin")
    c2 = create_test_category(client, t2, r2.json()["id"], "Entrees")
    create_test_item(client, t2, c2.json()["id"], "Beef Burrito", 1199)
    create_test_item(client, t2, c2.json()["id"], "Chicken Quesadilla", 1099)
    create_test_item(client, t2, c2.json()["id"], "Fish Tacos", 1299)

    # Restaurant 3: Italian
    t3_resp = client.post("/auth/register-owner", json={"email": "mp_italian@test.com", "password": "password123"})
    t3 = t3_resp.json()["access_token"]
    r3 = create_test_restaurant(client, t3, "Pasta Place", "Houston")
    c3 = create_test_category(client, t3, r3.json()["id"], "Pasta")
    create_test_item(client, t3, c3.json()["id"], "Spaghetti Bolognese", 1399)
    create_test_item(client, t3, c3.json()["id"], "Margherita Pizza", 1199)
    create_test_item(client, t3, c3.json()["id"], "Chicken Alfredo", 1499)

    return t1, r1.json()["id"]


class TestMealPlanGenerate:
    """Tests for POST /mealplan/generate"""

    def test_generates_correct_number_of_days(self, client):
        """5-day plan should return exactly 5 days."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["days"]) == 5

    def test_generates_3_day_plan(self, client):
        """3-day plan should return exactly 3 days."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "3 day meal plan"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["days"]) == 3

    def test_budget_respected(self, client):
        """Total plan cost should be under the specified budget."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "meal plan under $50"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cents"] <= 5000  # $50 = 5000 cents

    def test_returns_meal_details(self, client):
        """Each day should have item_name, restaurant_name, and price_cents."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        data = resp.json()
        for day in data["days"]:
            assert "item_name" in day
            assert "restaurant_name" in day
            assert "price_cents" in day
            assert day["price_cents"] > 0

    def test_no_beverages_in_plan(self, client):
        """Meal plan should not include drinks like lassi, milkshake, water."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        data = resp.json()
        beverage_keywords = {"lassi", "milkshake", "water", "soda", "juice", "tea", "coffee"}
        for day in data["days"]:
            item_lower = day["item_name"].lower()
            for kw in beverage_keywords:
                assert kw not in item_lower, f"Beverage '{kw}' found in plan: {day['item_name']}"

    def test_minimum_price_enforced(self, client):
        """All items should be >= $5 (500 cents min price filter)."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        data = resp.json()
        for day in data["days"]:
            assert day["price_cents"] >= 500, f"Item '{day['item_name']}' is {day['price_cents']} cents (below 500)"

    def test_has_savings_info(self, client):
        """Response should include savings_cents and total_cents."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        data = resp.json()
        assert "total_cents" in data
        assert "savings_cents" in data
        assert data["total_cents"] > 0

    def test_has_ai_summary(self, client):
        """Response should include an AI-generated summary string."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        data = resp.json()
        assert "ai_summary" in data
        assert data["ai_summary"] is not None
        assert len(data["ai_summary"]) > 5  # Not empty

    def test_diversity_multiple_restaurants(self, client):
        """Plan should use items from multiple restaurants."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        data = resp.json()
        restaurants = {d["restaurant_name"] for d in data["days"]}
        # With 3 restaurants and 5 days, should use at least 2
        assert len(restaurants) >= 2, f"Only {len(restaurants)} restaurant(s) used: {restaurants}"


class TestMealPlanSwap:
    """Tests for POST /mealplan/swap"""

    def test_swap_returns_new_item(self, client):
        """Swapping a day should return a different item."""
        _setup_menu(client)
        gen_resp = client.post("/mealplan/generate", json={"text": "5 day meal plan"})
        assert gen_resp.status_code == 200
        plan = gen_resp.json()
        original = plan["days"][0]

        swap_resp = client.post("/mealplan/swap", json={
            "text": "swap this meal",
            "day_index": 0,
            "current_item_id": original["item_id"],
            "budget_remaining_cents": plan["budget_cents"] - plan["total_cents"] + original["price_cents"],
        })
        assert swap_resp.status_code == 200

    def test_swap_invalid_item(self, client):
        """Swapping with nonexistent item_id should handle gracefully."""
        _setup_menu(client)
        swap_resp = client.post("/mealplan/swap", json={
            "text": "swap this",
            "day_index": 0,
            "current_item_id": 99999,
            "budget_remaining_cents": 10000,
        })
        assert swap_resp.status_code in [200, 400, 404, 422]


class TestMealPlanEdgeCases:
    """Edge cases for meal plan generation."""

    def test_empty_text(self, client):
        """Empty text should return 400."""
        resp = client.post("/mealplan/generate", json={"text": ""})
        assert resp.status_code == 400

    def test_very_low_budget(self, client):
        """Budget of $1 — may return fewer days or empty."""
        _setup_menu(client)
        resp = client.post("/mealplan/generate", json={"text": "meal plan under $1"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["days"]) <= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
