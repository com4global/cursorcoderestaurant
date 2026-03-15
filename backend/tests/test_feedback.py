"""Tests for post-order feedback and escalation."""
from datetime import datetime, timedelta

import pytest
from app import models
from tests.conftest import (
    get_auth_header,
    register_user,
    create_test_restaurant,
    create_test_category,
    create_test_item,
)


def _user_token(client, email="fb_user@test.com"):
    r = register_user(client, email=email)
    assert r.status_code == 200
    return r.json()["access_token"]


def _owner_token(client, email="fb_owner@test.com"):
    r = register_user(client, email=email, role="owner")
    assert r.status_code == 200
    return r.json()["access_token"]


class TestSubmitFeedback:
    def test_submit_feedback_requires_auth(self, client):
        r = client.post("/feedback", json={"order_id": 1, "rating": 5})
        assert r.status_code == 401

    def test_submit_feedback_completed_order_success(self, client, db):
        customer_token = _user_token(client, "fb_cust1@test.com")
        owner_token = _owner_token(client, "fb_own1@test.com")
        rest = create_test_restaurant(client, owner_token, "FB Rest")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Biryani", 1299)
        user = db.query(models.User).filter(models.User.email == "fb_cust1@test.com").first()
        order = models.Order(
            user_id=user.id,
            restaurant_id=rid,
            status="completed",
            total_cents=1299,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        r = client.post(
            "/feedback",
            headers=get_auth_header(customer_token),
            json={"order_id": order.id, "rating": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["order_id"] == order.id
        assert data["rating"] == 5
        assert data["escalated"] is False

    def test_submit_feedback_with_issues_escalated(self, client, db):
        customer_token = _user_token(client, "fb_cust2@test.com")
        owner_token = _owner_token(client, "fb_own2@test.com")
        rest = create_test_restaurant(client, owner_token, "FB Rest 2")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Rice", 599)
        user = db.query(models.User).filter(models.User.email == "fb_cust2@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="completed", total_cents=599)
        db.add(order)
        db.commit()
        db.refresh(order)
        r = client.post(
            "/feedback",
            headers=get_auth_header(customer_token),
            json={
                "order_id": order.id,
                "rating": 2,
                "issues": ["cold_food", "taste_bad"],
                "comment": "Food was cold",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["rating"] == 2
        assert data["escalated"] is True
        assert set(data["issues"]) == {"cold_food", "taste_bad"}
        assert data["comment"] == "Food was cold"

    def test_submit_feedback_already_submitted_returns_400(self, client, db):
        customer_token = _user_token(client, "fb_cust3@test.com")
        owner_token = _owner_token(client, "fb_own3@test.com")
        rest = create_test_restaurant(client, owner_token, "FB Rest 3")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Soup", 399)
        user = db.query(models.User).filter(models.User.email == "fb_cust3@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="completed", total_cents=399)
        db.add(order)
        db.commit()
        db.refresh(order)
        client.post(
            "/feedback",
            headers=get_auth_header(customer_token),
            json={"order_id": order.id, "rating": 4},
        )
        r2 = client.post(
            "/feedback",
            headers=get_auth_header(customer_token),
            json={"order_id": order.id, "rating": 3},
        )
        assert r2.status_code == 400
        assert "already" in r2.json()["detail"].lower()

    def test_submit_feedback_pending_order_returns_400(self, client, db):
        customer_token = _user_token(client, "fb_cust4@test.com")
        owner_token = _owner_token(client, "fb_own4@test.com")
        rest = create_test_restaurant(client, owner_token, "FB Rest 4")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Naan", 199)
        user = db.query(models.User).filter(models.User.email == "fb_cust4@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="confirmed", total_cents=199)
        db.add(order)
        db.commit()
        db.refresh(order)
        r = client.post(
            "/feedback",
            headers=get_auth_header(customer_token),
            json={"order_id": order.id, "rating": 5},
        )
        assert r.status_code == 400
        assert "completed" in r.json()["detail"].lower()


class TestGetOrderFeedback:
    def test_get_feedback_returns_feedback(self, client, db):
        customer_token = _user_token(client, "fb_get1@test.com")
        owner_token = _owner_token(client, "fb_get1_own@test.com")
        rest = create_test_restaurant(client, owner_token, "Get Rest")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Item", 999)
        user = db.query(models.User).filter(models.User.email == "fb_get1@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="completed", total_cents=999)
        db.add(order)
        db.commit()
        db.refresh(order)
        fb = models.OrderFeedback(order_id=order.id, user_id=user.id, rating=4)
        db.add(fb)
        db.commit()
        r = client.get(f"/orders/{order.id}/feedback", headers=get_auth_header(customer_token))
        assert r.status_code == 200
        assert r.json()["rating"] == 4

    def test_get_feedback_none_returns_null(self, client, db):
        customer_token = _user_token(client, "fb_get2@test.com")
        owner_token = _owner_token(client, "fb_get2_own@test.com")
        rest = create_test_restaurant(client, owner_token, "Get Rest 2")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Item", 888)
        user = db.query(models.User).filter(models.User.email == "fb_get2@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="completed", total_cents=888)
        db.add(order)
        db.commit()
        db.refresh(order)
        r = client.get(f"/orders/{order.id}/feedback", headers=get_auth_header(customer_token))
        assert r.status_code == 200
        assert r.json() is None


class TestOwnerComplaints:
    def test_owner_complaints_list_escalated_only(self, client, db):
        owner_token = _owner_token(client, "fb_own_c@test.com")
        customer_token = _user_token(client, "fb_cust_c@test.com")
        rest = create_test_restaurant(client, owner_token, "Complaint Rest")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Dish", 1099)
        user = db.query(models.User).filter(models.User.email == "fb_cust_c@test.com").first()
        order = models.Order(user_id=user.id, restaurant_id=rid, status="completed", total_cents=1099)
        db.add(order)
        db.commit()
        db.refresh(order)
        fb = models.OrderFeedback(
            order_id=order.id,
            user_id=user.id,
            rating=2,
            issues='["cold_food"]',
            comment="Cold",
        )
        db.add(fb)
        db.commit()
        r = client.get(
            f"/owner/restaurants/{rid}/complaints",
            headers=get_auth_header(owner_token),
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["rating"] == 2
        assert "cold_food" in data[0]["issues"]


class TestMyOrdersFeedbackEligible:
    def test_my_orders_includes_feedback_eligible_and_feedback(self, client, db):
        customer_token = _user_token(client, "fb_my@test.com")
        owner_token = _owner_token(client, "fb_my_own@test.com")
        rest = create_test_restaurant(client, owner_token, "My Rest")
        rid = rest.json()["id"]
        cat = create_test_category(client, owner_token, rid, "Mains")
        cid = cat.json()["id"]
        create_test_item(client, owner_token, cid, "Food", 799)
        user = db.query(models.User).filter(models.User.email == "fb_my@test.com").first()
        order = models.Order(
            user_id=user.id,
            restaurant_id=rid,
            status="completed",
            total_cents=799,
        )
        order.status_updated_at = datetime.utcnow() - timedelta(minutes=45)
        db.add(order)
        db.commit()
        db.refresh(order)
        r = client.get("/my-orders", headers=get_auth_header(customer_token))
        assert r.status_code == 200
        orders = r.json()
        o = next((x for x in orders if x["id"] == order.id), None)
        assert o is not None
        assert "feedback_eligible" in o
        assert "feedback" in o
        assert o["feedback"] is None
        assert o["feedback_eligible"] is True
