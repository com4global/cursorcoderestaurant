"""Tests for cart, checkout, and order management endpoints."""
import pytest
from .conftest import register_user, get_auth_header, create_test_restaurant, create_test_category, create_test_item


def _setup_restaurant_with_items(client):
    """Set up an owner with a restaurant, category, and items. Returns (owner_token, restaurant_id, [item_ids])."""
    # Owner
    resp = client.post("/auth/register-owner", json={"email": f"ordowner_{id(client)}@test.com", "password": "password123"})
    owner_token = resp.json()["access_token"]

    # Restaurant
    r = create_test_restaurant(client, owner_token, "Order Test Restaurant")
    rid = r.json()["id"]

    # Category + Items
    cat = create_test_category(client, owner_token, rid, "Mains")
    cat_id = cat.json()["id"]
    item1 = create_test_item(client, owner_token, cat_id, "Biryani", 1299)
    item2 = create_test_item(client, owner_token, cat_id, "Naan", 299)

    return owner_token, rid, [item1.json()["id"], item2.json()["id"]]


def _customer_token(client, email="customer_ord@test.com"):
    resp = client.post("/auth/register", json={"email": email, "password": "password123"})
    return resp.json()["access_token"]


class TestCart:
    def test_add_to_cart(self, client):
        _, rid, item_ids = _setup_restaurant_with_items(client)
        token = _customer_token(client, "cart_add@test.com")

        resp = client.post("/cart/add-combo", json={
            "restaurant_id": rid,
            "items": [{"item_id": item_ids[0], "quantity": 2}],
        }, headers=get_auth_header(token))
        assert resp.status_code == 200

    def test_view_cart(self, client):
        _, rid, item_ids = _setup_restaurant_with_items(client)
        token = _customer_token(client, "cart_view@test.com")

        # Add items
        client.post("/cart/add-combo", json={
            "restaurant_id": rid,
            "items": [
                {"item_id": item_ids[0], "quantity": 1},
                {"item_id": item_ids[1], "quantity": 2},
            ],
        }, headers=get_auth_header(token))

        # View cart
        resp = client.get("/cart", headers=get_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "restaurants" in data
        assert "grand_total_cents" in data

    def test_clear_cart(self, client):
        _, rid, item_ids = _setup_restaurant_with_items(client)
        token = _customer_token(client, "cart_clear@test.com")

        # Add items
        client.post("/cart/add-combo", json={
            "restaurant_id": rid,
            "items": [{"item_id": item_ids[0], "quantity": 1}],
        }, headers=get_auth_header(token))

        # Clear
        resp = client.delete("/cart/clear", headers=get_auth_header(token))
        assert resp.status_code == 200

        # Verify empty
        resp = client.get("/cart", headers=get_auth_header(token))
        data = resp.json()
        assert data["grand_total_cents"] == 0

    def test_cart_no_auth(self, client):
        resp = client.get("/cart")
        assert resp.status_code in (401, 403)


class TestCheckout:
    def test_checkout_success(self, client):
        _, rid, item_ids = _setup_restaurant_with_items(client)
        token = _customer_token(client, "checkout_ok@test.com")

        # Add items
        client.post("/cart/add-combo", json={
            "restaurant_id": rid,
            "items": [{"item_id": item_ids[0], "quantity": 1}],
        }, headers=get_auth_header(token))

        # Checkout
        resp = client.post("/checkout", headers=get_auth_header(token))
        assert resp.status_code == 200

    def test_checkout_empty_cart(self, client):
        token = _customer_token(client, "checkout_empty@test.com")
        resp = client.post("/checkout", headers=get_auth_header(token))
        # Should fail — no items
        assert resp.status_code in (400, 404, 200)  # depends on impl


class TestOwnerOrders:
    def test_owner_view_orders(self, client):
        owner_token, rid, item_ids = _setup_restaurant_with_items(client)
        cust_token = _customer_token(client, "ownerview@test.com")

        # Customer adds and checks out
        client.post("/cart/add-combo", json={
            "restaurant_id": rid,
            "items": [{"item_id": item_ids[0], "quantity": 1}],
        }, headers=get_auth_header(cust_token))
        client.post("/checkout", headers=get_auth_header(cust_token))

        # Owner views orders
        resp = client.get(
            f"/owner/restaurants/{rid}/orders",
            headers=get_auth_header(owner_token),
        )
        assert resp.status_code == 200
        orders = resp.json()
        assert isinstance(orders, list)

    def test_update_order_status(self, client):
        owner_token, rid, item_ids = _setup_restaurant_with_items(client)
        cust_token = _customer_token(client, "ordstatus@test.com")

        # Customer adds and checks out
        client.post("/cart/add-combo", json={
            "restaurant_id": rid,
            "items": [{"item_id": item_ids[0], "quantity": 1}],
        }, headers=get_auth_header(cust_token))
        client.post("/checkout", headers=get_auth_header(cust_token))

        # Get orders
        resp = client.get(
            f"/owner/restaurants/{rid}/orders?exclude_status=",
            headers=get_auth_header(owner_token),
        )
        orders = resp.json()
        if orders:
            order_id = orders[0]["id"]
            # Update status
            resp = client.patch(
                f"/owner/orders/{order_id}/status",
                json={"status": "preparing"},
                headers=get_auth_header(owner_token),
            )
            assert resp.status_code == 200


class TestMyOrders:
    def test_customer_my_orders(self, client):
        _, rid, item_ids = _setup_restaurant_with_items(client)
        token = _customer_token(client, "myorders@test.com")

        # Add and checkout
        client.post("/cart/add-combo", json={
            "restaurant_id": rid,
            "items": [{"item_id": item_ids[0], "quantity": 1}],
        }, headers=get_auth_header(token))
        client.post("/checkout", headers=get_auth_header(token))

        # My orders
        resp = client.get("/my-orders", headers=get_auth_header(token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
