"""
Layer 3: End-to-End Search Pipeline Smoke Tests.

Tests the full chain: user text → /search/intent → intent extraction → DB query → ranked results.
"""
import pytest
from .conftest import get_auth_header, create_test_restaurant, create_test_category, create_test_item


def _setup_diverse_menu(client):
    """Create restaurants with varied cuisine for pipeline testing."""
    # Indian restaurant
    t1_resp = client.post("/auth/register-owner", json={"email": "pipe_a@test.com", "password": "password123"})
    t1 = t1_resp.json()["access_token"]
    r1 = create_test_restaurant(client, t1, "Curry Palace", "Dallas")
    c1 = create_test_category(client, t1, r1.json()["id"], "Indian Mains")
    create_test_item(client, t1, c1.json()["id"], "Chicken Biryani", 1599)
    create_test_item(client, t1, c1.json()["id"], "Veg Thali", 1199)
    create_test_item(client, t1, c1.json()["id"], "Paneer Butter Masala", 1399)

    # Pizza restaurant
    t2_resp = client.post("/auth/register-owner", json={"email": "pipe_b@test.com", "password": "password123"})
    t2 = t2_resp.json()["access_token"]
    r2 = create_test_restaurant(client, t2, "Pizza Express", "Austin")
    c2 = create_test_category(client, t2, r2.json()["id"], "Pizzas")
    create_test_item(client, t2, c2.json()["id"], "Margherita Pizza", 999)
    create_test_item(client, t2, c2.json()["id"], "Pepperoni Pizza", 1299)

    # Cheap restaurant
    t3_resp = client.post("/auth/register-owner", json={"email": "pipe_c@test.com", "password": "password123"})
    t3 = t3_resp.json()["access_token"]
    r3 = create_test_restaurant(client, t3, "Budget Bites", "Houston")
    c3 = create_test_category(client, t3, r3.json()["id"], "Value Menu")
    create_test_item(client, t3, c3.json()["id"], "Chicken Wings", 799)
    create_test_item(client, t3, c3.json()["id"], "Veg Burger", 599)


class TestSearchIntentPipeline:
    """Full pipeline: /search/intent processes natural language → returns results."""

    def test_simple_dish_search(self, client):
        """'pizza' should return pizza items."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "pizza"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) > 0
        pizza_results = [r for r in data["results"] if "pizza" in r["item_name"].lower()]
        assert len(pizza_results) > 0

    def test_price_constrained_search(self, client):
        """'pizza under $10' should return pizza items under $10."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "pizza under $10"})
        assert resp.status_code == 200
        data = resp.json()
        if data["results"]:
            for r in data["results"]:
                assert r["price_cents"] <= 1000, f"{r['item_name']} is {r['price_cents']} cents"

    def test_natural_language_query(self, client):
        """'I want something cheap' should return results."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "I want something cheap"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) > 0

    def test_protein_filter(self, client):
        """'chicken' should return chicken items."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "chicken"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) > 0
        chicken_results = [r for r in data["results"] if "chicken" in r["item_name"].lower()]
        assert len(chicken_results) > 0

    def test_recommendation_mode(self, client):
        """'what should I eat' should return diverse results."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "what should I eat"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) > 0

    def test_best_value_returned(self, client):
        """Search results should include best_value field."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "biryani"})
        assert resp.status_code == 200
        data = resp.json()
        assert "best_value" in data

    def test_meal_plan_detection(self, client):
        """'5 day meal plan' via /search/intent should still return 200."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "5 day meal plan"})
        assert resp.status_code == 200

    def test_empty_results_graceful(self, client):
        """Search for nonexistent item should return 200 with results array."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "xyznonexistent123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_multi_word_dish(self, client):
        """'chicken biryani' should find items matching both words."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "chicken biryani"})
        assert resp.status_code == 200
        data = resp.json()
        if data["results"]:
            top = data["results"][0]["item_name"].lower()
            assert "chicken" in top or "biryani" in top

    def test_diet_filter_veg(self, client):
        """'vegetarian food' should return results (may include fallback)."""
        _setup_diverse_menu(client)
        resp = client.post("/search/intent", json={"text": "vegetarian food"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
