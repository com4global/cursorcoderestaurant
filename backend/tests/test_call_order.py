"""Tests for the isolated AI call-order session and turn APIs."""

from datetime import datetime, timedelta
import json

from app import models, sarvam_service
from app.config import settings
from tests.conftest import (
    create_test_category,
    create_test_item,
    create_test_restaurant,
    get_auth_header,
    register_user,
)


def _owner_token(client, email="call_owner@test.com"):
    response = register_user(client, email=email, password="password123", role="owner")
    assert response.status_code == 200
    return response.json()["access_token"]


def _enable_call_order_llm(monkeypatch):
    monkeypatch.setattr(settings, "call_order_llm_orchestrator", True)
    monkeypatch.setenv("SARVAM_API_KEY", "test-sarvam-key")


class TestCallOrderSession:
    def test_create_session_returns_greeting(self, client):
        response = client.post("/api/call-order/session", json={"language": "ta-IN"})
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"]
        assert data["language"] == "ta-IN"
        assert data["assistant_reply"]
        assert data["history"][0]["role"] == "assistant"

    def test_get_missing_session_returns_404(self, client):
        response = client.get("/api/call-order/session/does-not-exist")
        assert response.status_code == 404

    def test_get_expired_session_returns_404(self, client, db):
        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        record = db.query(models.CallOrderSession).filter(
            models.CallOrderSession.session_id == session["session_id"]
        ).first()
        record.updated_at = datetime.utcnow() - timedelta(days=2)
        db.commit()

        response = client.get(f"/api/call-order/session/{session['session_id']}")
        assert response.status_code == 404
        assert db.query(models.CallOrderSession).filter(
            models.CallOrderSession.session_id == session["session_id"]
        ).first() is None


class TestCallOrderTurn:
    def test_turn_returns_clarification_for_complex_dish_name(self, client):
        owner_token = _owner_token(client, "dish_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Chettinad House", city="Chennai")
        restaurant_id = restaurant.json()["id"]
        category = create_test_category(client, owner_token, restaurant_id, name="Gravy")
        category_id = category.json()["id"]
        create_test_item(client, owner_token, category_id, name="Nattu Kozhi Kuzhambu", price_cents=1699)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I want nattu kazghi kolampu"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "not available" not in data["assistant_reply"].lower()
        assert data["suggestions"]
        assert any(suggestion["name"] == "Nattu Kozhi Kuzhambu" for suggestion in data["suggestions"])

    def test_turn_asks_for_clarification_when_two_items_are_close_matches(self, client):
        owner_token = _owner_token(client, "ambiguous_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Saravana Bhavan", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breakfast")
        create_test_item(client, owner_token, category.json()["id"], name="Plain Dosa", price_cents=899)
        create_test_item(client, owner_token, category.json()["id"], name="Masala Dosa", price_cents=1099)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add dosa"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "which one did you mean" in data["assistant_reply"].lower()
        assert data["pending_action"] is None
        assert len(data["suggestions"]) >= 2
        assert {suggestion["name"] for suggestion in data["suggestions"]} >= {"Plain Dosa", "Masala Dosa"}

    def test_turn_handles_dish_and_restaurant_in_same_sentence(self, client):
        owner_token = _owner_token(client, "combined_sentence_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma Restaurant", city="Chicago")
        aroma_category = create_test_category(client, owner_token, aroma.json()["id"], name="Soup")
        create_test_item(client, owner_token, aroma_category.json()["id"], name="Mutton Bone Soup", price_cents=1299)

        other = create_test_restaurant(client, owner_token, name="Test Restaurant", city="Chicago")
        other_category = create_test_category(client, owner_token, other.json()["id"], name="Soup")
        create_test_item(client, owner_token, other_category.json()["id"], name="Tomato Soup", price_cents=799)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={
                "session_id": session["session_id"],
                "transcript": "I'd like to order some mutton bone soup from Aroma Restaurant.",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Mutton Bone Soup"
        assert data["pending_action"]["item"]["restaurant_name"] == "Aroma Restaurant"
        assert data["selected_restaurant"]["name"] == "Aroma Restaurant"

    def test_turn_treats_generic_restaurant_selection_as_context_only(self, client):
        owner_token = _owner_token(client, "generic_restaurant_selection_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I would like to eat something from Aroma."},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["pending_action"] is None
        assert "aroma" in data["assistant_reply"].lower()

    def test_turn_treats_order_from_restaurant_without_dish_as_context_only(self, client):
        owner_token = _owner_token(client, "order_from_restaurant_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I would like to order from Aroma."},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["pending_action"] is None
        assert "aroma" in data["assistant_reply"].lower()

    def test_turn_treats_stt_maroma_restaurant_request_as_context_only(self, client):
        owner_token = _owner_token(client, "maroma_restaurant_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I'd like to order some food from Maroma."},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["pending_action"] is None
        assert data["assistant_reply"] == "I found Aroma. Tell me the dish you want from there."

    def test_llm_orchestrator_can_select_restaurant(self, client, monkeypatch):
        _enable_call_order_llm(monkeypatch)
        owner_token = _owner_token(client, "llm_restaurant_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)

        monkeypatch.setattr(
            sarvam_service,
            "chat_completion",
            lambda *_args, **_kwargs: json.dumps({
                "reply": "I found Aroma. Tell me the dish you want from there.",
                "action": "select_restaurant",
                "restaurant_id": aroma.json()["id"],
                "item_id": None,
                "quantity": 1,
                "use_pending_item": False,
            }),
        )

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I'd like to order from Aroma."},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["assistant_reply"] == "I found Aroma. Tell me the dish you want from there."

    def test_llm_orchestrator_can_ask_item_clarification_for_options_question(self, client, monkeypatch):
        _enable_call_order_llm(monkeypatch)
        owner_token = _owner_token(client, "llm_options_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        butter_naan = create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)
        create_test_item(client, owner_token, category.json()["id"], name="Garlic Naan", price_cents=390)

        butter_naan_id = butter_naan.json()["id"]
        monkeypatch.setattr(
            sarvam_service,
            "chat_completion",
            lambda *_args, **_kwargs: json.dumps({
                "reply": "At Aroma I have Butter Naan and Garlic Naan. Which one do you want?",
                "action": "ask_item_clarification",
                "restaurant_id": aroma.json()["id"],
                "item_id": butter_naan_id,
                "quantity": 1,
                "use_pending_item": False,
            }),
        )

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "What are all the options in the butter naan from Aroma?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["selected_item"]["name"] == "Butter Naan"
        assert "which one do you want" in data["assistant_reply"].lower()
        assert {suggestion["name"] for suggestion in data["suggestions"]} >= {"Butter Naan", "Garlic Naan"}

    def test_llm_orchestrator_invalid_action_falls_back_to_heuristic(self, client, monkeypatch):
        _enable_call_order_llm(monkeypatch)
        owner_token = _owner_token(client, "llm_fallback_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)

        monkeypatch.setattr(
            sarvam_service,
            "chat_completion",
            lambda *_args, **_kwargs: json.dumps({
                "reply": "Bad output",
                "action": "invalid_action",
                "restaurant_id": None,
                "item_id": None,
                "quantity": 1,
                "use_pending_item": False,
            }),
        )

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I'd like to order something from Aroma."},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["assistant_reply"] == "I found Aroma. Tell me the dish you want from there."


class TestCallOrderRealtime:
    def test_realtime_session_bootstrap_returns_provider_and_tools(self, client, monkeypatch):
        monkeypatch.setattr(settings, "ai_call_realtime_enabled", True)
        monkeypatch.setattr(settings, "ai_call_provider", "vapi")
        monkeypatch.setattr(settings, "ai_call_provider_public_key", "public-key")
        monkeypatch.setattr(settings, "ai_call_provider_assistant_id", "assistant-123")

        response = client.post("/api/call-order/realtime/session", json={"language": "en-IN"})
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"]
        assert data["realtime"]["enabled"] is True
        assert data["realtime"]["provider"]["name"] == "vapi"
        assert data["realtime"]["provider"]["assistant_id"] == "assistant-123"
        assert any(tool["name"] == "find_restaurants" for tool in data["realtime"]["tools"])

    def test_realtime_session_bootstrap_returns_retell_provider_config(self, client, monkeypatch):
        monkeypatch.setattr(settings, "ai_call_realtime_enabled", True)
        monkeypatch.setattr(settings, "ai_call_provider", "retell")
        monkeypatch.setattr(settings, "ai_call_provider_agent_id", "retell-agent-default")
        monkeypatch.setattr(settings, "ai_call_provider_agent_id_en", "retell-agent-en")
        monkeypatch.setattr(settings, "retell_server_url", "https://example.com/api/call-order/realtime/retell-webhook")

        response = client.post("/api/call-order/realtime/session", json={"language": "en-IN"})
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"]
        assert data["realtime"]["enabled"] is True
        assert data["realtime"]["provider"]["name"] == "retell"
        assert data["realtime"]["provider"]["agent_id"] == "retell-agent-default"
        assert data["realtime"]["provider"]["agent_ids"]["en-IN"] == "retell-agent-en"
        assert data["realtime"]["provider"]["server_url"] == "https://example.com/api/call-order/realtime/retell-webhook"

    def test_realtime_find_restaurants_returns_matches(self, client):
        owner_token = _owner_token(client, "realtime_restaurant_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        cat1 = create_test_category(client, owner_token, aroma.json()["id"], name="Main")
        create_test_item(client, owner_token, cat1.json()["id"], name="Fried Rice", price_cents=999)
        anjappar = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        cat2 = create_test_category(client, owner_token, anjappar.json()["id"], name="Main")
        create_test_item(client, owner_token, cat2.json()["id"], name="Biryani", price_cents=1299)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/tools/find-restaurants",
            json={"session_id": session["session_id"], "query": "aroma"},
        )
        assert response.status_code == 200
        data = response.json()
        assert any(match["name"] == "Aroma" for match in data["restaurants"])

    def test_realtime_list_restaurants_returns_live_database_rows(self, client):
        owner_token = _owner_token(client, "realtime_restaurant_list_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        cat1 = create_test_category(client, owner_token, aroma.json()["id"], name="Main")
        create_test_item(client, owner_token, cat1.json()["id"], name="Fried Rice", price_cents=999)
        anjappar = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        cat2 = create_test_category(client, owner_token, anjappar.json()["id"], name="Main")
        create_test_item(client, owner_token, cat2.json()["id"], name="Biryani", price_cents=1299)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/tools/list-restaurants",
            json={"session_id": session["session_id"], "limit": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert any(match["name"] == "Aroma" for match in data["restaurants"])
        assert any(match["name"] == "Anjappar" for match in data["restaurants"])

    def test_realtime_list_restaurants_falls_back_for_noisy_availability_query(self, client):
        owner_token = _owner_token(client, "realtime_restaurant_list_noise_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        cat1 = create_test_category(client, owner_token, aroma.json()["id"], name="Main")
        create_test_item(client, owner_token, cat1.json()["id"], name="Fried Rice", price_cents=999)
        anjappar = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        cat2 = create_test_category(client, owner_token, anjappar.json()["id"], name="Main")
        create_test_item(client, owner_token, cat2.json()["id"], name="Biryani", price_cents=1299)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/tools/list-restaurants",
            json={"session_id": session["session_id"], "query": "either available restaurants", "limit": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["restaurants"]
        assert any(match["name"] == "Aroma" for match in data["restaurants"])
        assert any(match["name"] == "Anjappar" for match in data["restaurants"])

    def test_realtime_find_restaurants_matches_spoken_restaurant_variant(self, client):
        owner_token = _owner_token(client, "realtime_restaurant_variant_owner@test.com")
        anjappar = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        cat = create_test_category(client, owner_token, anjappar.json()["id"], name="Main")
        create_test_item(client, owner_token, cat.json()["id"], name="Biryani", price_cents=1299)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/tools/find-restaurants",
            json={"session_id": session["session_id"], "query": "is there a restaurant called anjapur here"},
        )
        assert response.status_code == 200
        data = response.json()
        assert any(match["name"] == "Anjappar" for match in data["restaurants"])

    def test_realtime_menu_returns_categories_and_suggestions(self, client):
        owner_token = _owner_token(client, "realtime_menu_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)
        create_test_item(client, owner_token, category.json()["id"], name="Garlic Naan", price_cents=390)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/tools/menu",
            json={"session_id": session["session_id"], "restaurant_id": aroma.json()["id"], "query": "naan"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["restaurant"]["name"] == "Aroma"
        assert any(category_data["name"] == "Breads" for category_data in data["categories"])
        assert any(item["name"] == "Butter Naan" for item in data["suggested_items"])

    def test_realtime_add_and_remove_item_updates_draft(self, client):
        owner_token = _owner_token(client, "realtime_draft_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        butter_naan = create_test_item(client, owner_token, category.json()["id"], name="Butter Naan", price_cents=350)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        add_response = client.post(
            "/api/call-order/realtime/tools/add-item",
            json={"session_id": session["session_id"], "item_id": butter_naan.json()["id"], "quantity": 2},
        )
        assert add_response.status_code == 200
        add_data = add_response.json()
        assert add_data["draft"]["draft_total_items"] == 2
        assert "Butter Naan" in add_data["summary"]

        remove_response = client.post(
            "/api/call-order/realtime/tools/remove-item",
            json={"session_id": session["session_id"], "item_id": butter_naan.json()["id"], "quantity": 1},
        )
        assert remove_response.status_code == 200
        remove_data = remove_response.json()
        assert remove_data["draft"]["draft_total_items"] == 1

    def test_realtime_draft_summary_returns_snapshot(self, client):
        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.get(f"/api/call-order/realtime/tools/draft-summary/{session['session_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["draft"]["session_id"] == session["session_id"]
        assert "draft order is empty" in data["summary"].lower()

    def test_realtime_start_checkout_requires_auth(self, client):
        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/tools/start-checkout",
            json={"session_id": session["session_id"]},
        )
        assert response.status_code in (401, 403)

    def test_realtime_start_checkout_materializes_draft_and_returns_checkout(self, client):
        owner_token = _owner_token(client, "realtime_checkout_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Curries")
        item = create_test_item(client, owner_token, category.json()["id"], name="Veg Kurma", price_cents=899)

        customer = register_user(client, email="realtime_checkout_customer@test.com", password="password123")
        token = customer.json()["access_token"]

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        add_response = client.post(
            "/api/call-order/realtime/tools/add-item",
            json={"session_id": session["session_id"], "item_id": item.json()["id"], "quantity": 2},
        )
        assert add_response.status_code == 200

        response = client.post(
            "/api/call-order/realtime/tools/start-checkout",
            json={"session_id": session["session_id"]},
            headers=get_auth_header(token),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["materialized_item_count"] == 2
        assert data["materialized_restaurant_count"] == 1
        assert data["draft"]["draft_total_items"] == 0
        assert data["checkout"]["session_id"] == "sim_dev"

        cart = client.get("/cart", headers=get_auth_header(token))
        assert cart.status_code == 200
        cart_data = cart.json()
        assert cart_data["grand_total_cents"] == 0

        orders = client.get("/my-orders", headers=get_auth_header(token))
        assert orders.status_code == 200
        orders_data = orders.json()
        assert any(order["total_cents"] == 1798 for order in orders_data)

    # ── Retell Custom Function endpoint tests ─────────────────────────────

    def test_retell_tool_list_restaurants_returns_data(self, client):
        owner_token = _owner_token(client, "retell_tool_list_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="RetellTestRestaurant", city="Chennai")
        cat = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, cat.json()["id"], name="Dosa", price_cents=500)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/retell-tool/list_restaurants",
            json={
                "args": {},
                "call": {"call_id": "test-retell-1", "agent_id": "agent_test", "metadata": {"sessionId": session["session_id"]}},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert any(r["name"] == "RetellTestRestaurant" for r in data["restaurants"])

    def test_retell_tool_get_menu_by_id(self, client):
        owner_token = _owner_token(client, "retell_tool_menu_id_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="RetellMenuTest", city="Chennai")
        cat = create_test_category(client, owner_token, restaurant.json()["id"], name="Snacks")
        create_test_item(client, owner_token, cat.json()["id"], name="Samosa", price_cents=200)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/retell-tool/get_restaurant_menu",
            json={
                "args": {"restaurant_id": restaurant.json()["id"]},
                "call": {"call_id": "test-retell-2", "agent_id": "agent_test", "metadata": {"sessionId": session["session_id"]}},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["restaurant"]["name"] == "RetellMenuTest"
        assert len(data["categories"]) >= 1
        assert any(i["name"] == "Samosa" for cat in data["categories"] for i in cat.get("items", []))

    def test_retell_tool_get_menu_by_name(self, client):
        owner_token = _owner_token(client, "retell_tool_menu_name_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="RetellNameTest", city="Chennai")
        cat = create_test_category(client, owner_token, restaurant.json()["id"], name="Curries")
        create_test_item(client, owner_token, cat.json()["id"], name="Paneer Butter Masala", price_cents=1200)

        session = client.post("/api/call-order/realtime/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/realtime/retell-tool/get_restaurant_menu",
            json={
                "args": {"restaurant_name": "RetellNameTest"},
                "call": {"call_id": "test-retell-3", "agent_id": "agent_test", "metadata": {"sessionId": session["session_id"]}},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["restaurant"]["name"] == "RetellNameTest"
        assert not data.get("error")

    def test_retell_tool_missing_session_id_returns_error(self, client):
        response = client.post(
            "/api/call-order/realtime/retell-tool/list_restaurants",
            json={
                "args": {},
                "call": {"call_id": "test-retell-no-session", "agent_id": "agent_test"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data or "Missing" in str(data)

    def test_turn_handles_acknowledgement_without_matching_fake_dish(self, client):
        owner_token = _owner_token(client, "acknowledgement_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, aroma.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Naan", price_cents=350)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "Naan from Aroma"},
        )
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "go ahead and add it"},
        )

        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "Okay"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "could not match okay there" not in data["assistant_reply"].lower()
        assert "another dish from aroma" in data["assistant_reply"].lower()

    def test_turn_keeps_restaurant_context_when_item_exists_only_elsewhere(self, client):
        owner_token = _owner_token(client, "restaurant_context_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        aroma_category = create_test_category(client, owner_token, aroma.json()["id"], name="Soup")
        create_test_item(client, owner_token, aroma_category.json()["id"], name="Tomato Soup", price_cents=799)

        anjappar = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        anjappar_category = create_test_category(client, owner_token, anjappar.json()["id"], name="Soup")
        create_test_item(client, owner_token, anjappar_category.json()["id"], name="Mutton Bone Soup", price_cents=1299)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        select_restaurant = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I'd like to order something from Aroma."},
        )
        assert select_restaurant.status_code == 200
        assert select_restaurant.json()["selected_restaurant"]["name"] == "Aroma"

        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "Mutton Bone Soup"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["pending_action"] is None
        assert "could not match mutton bone soup there" in data["assistant_reply"].lower()
        assert "anjappar" in data["assistant_reply"].lower()
        assert any(suggestion["restaurant_name"] == "Anjappar" for suggestion in data["suggestions"])

    def test_turn_does_not_switch_to_negatively_mentioned_restaurant(self, client):
        owner_token = _owner_token(client, "negative_restaurant_owner@test.com")
        aroma = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        aroma_cat = create_test_category(client, owner_token, aroma.json()["id"], name="Main")
        create_test_item(client, owner_token, aroma_cat.json()["id"], name="Fried Rice", price_cents=999)
        anjappar = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category = create_test_category(client, owner_token, anjappar.json()["id"], name="Soup")
        create_test_item(client, owner_token, category.json()["id"], name="Mutton Bone Soup", price_cents=1299)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        first = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "Bone Soup"},
        )
        assert first.status_code == 200
        assert first.json()["pending_action"] is not None

        correction = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I said from Aroma, not from Manjappar."},
        )
        assert correction.status_code == 200
        data = correction.json()
        assert data["selected_restaurant"]["name"] == "Aroma"
        assert data["pending_action"] is None
        reply = data["assistant_reply"].lower()
        assert "aroma" in reply
        assert "dish" in reply or "tell me" in reply

    def test_turn_matches_kurma_alias_variants(self, client):
        owner_token = _owner_token(client, "kurma_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Sides")
        create_test_item(client, owner_token, category.json()["id"], name="Veg Kurma", price_cents=899)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add veg korma"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Veg Kurma"

    def test_turn_matches_kuruma_alias_variants(self, client):
        owner_token = _owner_token(client, "kuruma_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Sides")
        create_test_item(client, owner_token, category.json()["id"], name="Veg Kurma", price_cents=899)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add veg kuruma"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Veg Kurma"

    def test_turn_matches_idiyappam_alias_variants(self, client):
        owner_token = _owner_token(client, "idiyappam_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Saravana Bhavan", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breakfast")
        create_test_item(client, owner_token, category.json()["id"], name="Idiyappam", price_cents=799)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i want idiappom"},
        )
        assert response.status_code == 200
        data = response.json()
        assert any(suggestion["name"] == "Idiyappam" for suggestion in data["suggestions"])

    def test_turn_matches_dosa_alias_variants(self, client):
        owner_token = _owner_token(client, "dosa_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Saravana Bhavan", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breakfast")
        create_test_item(client, owner_token, category.json()["id"], name="Masala Dosa", price_cents=1099)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add masala dosai"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Masala Dosa"

    def test_turn_matches_idli_alias_variants(self, client):
        owner_token = _owner_token(client, "idli_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breakfast")
        create_test_item(client, owner_token, category.json()["id"], name="Idli", price_cents=599)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i want idly"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Idli"

    def test_turn_matches_uthappam_alias_variants(self, client):
        owner_token = _owner_token(client, "uthappam_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Murugan Idli Shop", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breakfast")
        create_test_item(client, owner_token, category.json()["id"], name="Onion Uthappam", price_cents=999)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add onion uttapam"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Onion Uthappam"

    def test_turn_matches_vadai_alias_variants(self, client):
        owner_token = _owner_token(client, "vada_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breakfast")
        create_test_item(client, owner_token, category.json()["id"], name="Medu Vada", price_cents=699)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add medu vadai"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Medu Vada"

    def test_turn_matches_chicken_sixty_five_variant(self, client):
        owner_token = _owner_token(client, "sixtyfive_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Starters")
        create_test_item(client, owner_token, category.json()["id"], name="Chicken 65", price_cents=1299)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add chicken sixty five"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Chicken 65"

    def test_turn_matches_gobi_sixty_five_variant(self, client):
        owner_token = _owner_token(client, "gobi65_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Starters")
        create_test_item(client, owner_token, category.json()["id"], name="Gobi 65", price_cents=999)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i want gobi six five"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Gobi 65"

    def test_turn_matches_chettinad_alias_variants(self, client):
        owner_token = _owner_token(client, "chettinad_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Chettinad House", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Chettinad Chicken", price_cents=1599)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add chettinaad chicken"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Chettinad Chicken"

    def test_turn_matches_sambhar_alias_variants(self, client):
        owner_token = _owner_token(client, "sambar_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Saravana Bhavan", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Rice")
        create_test_item(client, owner_token, category.json()["id"], name="Sambar Rice", price_cents=1099)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i want sambhar rice"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Sambar Rice"

    def test_turn_matches_raasam_alias_variants(self, client):
        owner_token = _owner_token(client, "rasam_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Soup")
        create_test_item(client, owner_token, category.json()["id"], name="Tomato Rasam", price_cents=699)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add tomato raasam"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Tomato Rasam"

    def test_turn_matches_thaali_variant(self, client):
        owner_token = _owner_token(client, "thali_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Saravana Bhavan", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Meals")
        create_test_item(client, owner_token, category.json()["id"], name="South Indian Thali", price_cents=1499)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add south indian thaali"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "South Indian Thali"

    def test_turn_matches_mini_meal_singular_plural_variant(self, client):
        owner_token = _owner_token(client, "mini_meal_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Meals")
        create_test_item(client, owner_token, category.json()["id"], name="Mini Meals", price_cents=1199)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i want mini meal"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Mini Meals"

    def test_turn_matches_chapati_alias_variants(self, client):
        owner_token = _owner_token(client, "chapathi_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Chapathi", price_cents=399)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add chapati"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Chapathi"

    def test_turn_matches_puri_alias_variants(self, client):
        owner_token = _owner_token(client, "poori_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Breads")
        create_test_item(client, owner_token, category.json()["id"], name="Poori", price_cents=599)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i want puri"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Poori"

    def test_turn_matches_panir_alias_variants(self, client):
        owner_token = _owner_token(client, "paneer_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="A2B", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Curries")
        create_test_item(client, owner_token, category.json()["id"], name="Paneer Butter Masala", price_cents=1399)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add panir butter masala"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Paneer Butter Masala"

    def test_turn_matches_chukka_alias_variants(self, client):
        owner_token = _owner_token(client, "sukka_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Chettinad House", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Mutton Sukka", price_cents=1799)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i want mutton chukka"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["item"]["name"] == "Mutton Sukka"

    def test_turn_asks_for_restaurant_when_ordering_without_context(self, client):
        owner_token = _owner_token(client, "rest_owner@test.com")
        create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I want to order food"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "restaurant" in data["assistant_reply"].lower()

    def test_turn_requires_valid_session(self, client):
        response = client.post(
            "/api/call-order/turn",
            json={"session_id": "missing", "transcript": "hello"},
        )
        assert response.status_code == 404

    def test_turn_can_confirm_add_to_draft_cart(self, client):
        owner_token = _owner_token(client, "confirm_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Chicken Biryani", price_cents=1499)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        first = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "I want two chicken biryani"},
        )
        assert first.status_code == 200
        first_data = first.json()
        assert first_data["pending_action"] is not None

        confirm = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "yes"},
        )
        assert confirm.status_code == 200
        data = confirm.json()
        assert data["draft_total_items"] == 2
        assert data["draft_cart"][0]["name"] == "Chicken Biryani"
        assert data["draft_cart"][0]["quantity"] == 2

    def test_turn_can_confirm_selected_item_with_natural_language(self, client):
        owner_token = _owner_token(client, "natural_confirm_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Aroma", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Hyderabadi Chicken Dum Biryani", price_cents=1799)
        create_test_item(client, owner_token, category.json()["id"], name="Chicken 65 Biryani", price_cents=1699)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        clarify = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "i would like to order one chicken biryani"},
        )
        assert clarify.status_code == 200
        clarify_data = clarify.json()
        assert "which one did you mean" in clarify_data["assistant_reply"].lower()

        choose_item = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "Hyderabadi Chicken Biryani"},
        )
        assert choose_item.status_code == 200
        choose_data = choose_item.json()
        assert choose_data["pending_action"] is not None
        assert choose_data["pending_action"]["item"]["name"] == "Hyderabadi Chicken Dum Biryani"

        confirm = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "go ahead and order that"},
        )
        assert confirm.status_code == 200
        data = confirm.json()
        assert data["draft_total_items"] == 1
        assert data["draft_cart"][0]["name"] == "Hyderabadi Chicken Dum Biryani"

    def test_turn_can_remove_from_draft_cart(self, client):
        owner_token = _owner_token(client, "remove_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Parotta", price_cents=499)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        client.post("/api/call-order/turn", json={"session_id": session["session_id"], "transcript": "add two parotta"})
        client.post("/api/call-order/turn", json={"session_id": session["session_id"], "transcript": "yes"})

        remove = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "remove one parotta"},
        )
        assert remove.status_code == 200
        data = remove.json()
        assert data["draft_total_items"] == 1
        assert data["draft_cart"][0]["quantity"] == 1

    def test_turn_can_summarize_draft_cart(self, client):
        owner_token = _owner_token(client, "summary_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Parotta", price_cents=499)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        client.post("/api/call-order/turn", json={"session_id": session["session_id"], "transcript": "add parotta"})
        client.post("/api/call-order/turn", json={"session_id": session["session_id"], "transcript": "yes"})

        summary = client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "what is in my order"},
        )
        assert summary.status_code == 200
        assert "draft order" in summary.json()["assistant_reply"].lower()

    def test_get_session_returns_persisted_turn_state(self, client):
        owner_token = _owner_token(client, "persist_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Parotta", price_cents=499)

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add two parotta"},
        )
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "yes"},
        )

        restored = client.get(f"/api/call-order/session/{session['session_id']}")
        assert restored.status_code == 200
        data = restored.json()
        assert data["draft_total_items"] == 2
        assert data["draft_cart"][0]["name"] == "Parotta"
        assert data["history"][-1]["role"] == "assistant"


def test_call_order_admin_summary_requires_owner_or_admin(client):
    customer = register_user(client, email="customer@example.com", password="secret123", role="customer")
    token = customer.json()["access_token"]

    response = client.get(
        "/api/call-order/admin/summary",
        headers=get_auth_header(token),
    )

    assert response.status_code == 403


def test_call_order_admin_summary_reports_active_and_expired_sessions(client, db):
    owner_token = _owner_token(client, "callowner@example.com")

    active_session = models.CallOrderSession(
        session_id="active-session",
        language="en-IN",
        state="connected",
        history_json="[]",
        draft_cart_json="[]",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    expired_session = models.CallOrderSession(
        session_id="expired-session",
        language="en-IN",
        state="connected",
        history_json="[]",
        draft_cart_json="[]",
        created_at=datetime.utcnow() - timedelta(days=3),
        updated_at=datetime.utcnow() - timedelta(days=2),
    )
    recent_inactive_session = models.CallOrderSession(
        session_id="recent-inactive-session",
        language="en-IN",
        state="connected",
        history_json="[]",
        draft_cart_json="[]",
        created_at=datetime.utcnow() - timedelta(hours=6),
        updated_at=datetime.utcnow() - timedelta(hours=2),
    )
    db.add(active_session)
    db.add(expired_session)
    db.add(recent_inactive_session)
    db.commit()

    response = client.get(
        "/api/call-order/admin/summary",
        headers=get_auth_header(owner_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ttl_minutes"] == 24 * 60
    assert data["total_sessions"] == 3
    assert data["active_sessions"] == 2
    assert data["expired_sessions"] == 1
    assert data["sessions_created_last_24h"] == 2
    assert data["sessions_created_last_7d"] == 3
    assert data["sessions_updated_last_24h"] == 2
    assert data["oldest_active_updated_at"] is not None
    assert data["newest_active_updated_at"] is not None


class TestCallOrderFinalize:
    def test_finalize_requires_auth(self, client):
        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        response = client.post(f"/api/call-order/session/{session['session_id']}/finalize")
        assert response.status_code in (401, 403)

    def test_finalize_moves_draft_items_into_existing_cart(self, client):
        owner_token = _owner_token(client, "finalize_owner@test.com")
        restaurant = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category = create_test_category(client, owner_token, restaurant.json()["id"], name="Main")
        create_test_item(client, owner_token, category.json()["id"], name="Chicken Biryani", price_cents=1499)

        customer = register_user(client, email="finalize_customer@test.com", password="password123")
        token = customer.json()["access_token"]

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add two chicken biryani"},
        )
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "yes"},
        )

        finalize = client.post(
            f"/api/call-order/session/{session['session_id']}/finalize",
            headers=get_auth_header(token),
        )
        assert finalize.status_code == 200
        data = finalize.json()
        assert data["draft_total_items"] == 0
        assert data["materialized_item_count"] == 2
        assert data["materialized_restaurant_count"] == 1

        cart = client.get("/cart", headers=get_auth_header(token))
        assert cart.status_code == 200
        cart_data = cart.json()
        assert cart_data["grand_total_cents"] == 2998
        assert cart_data["restaurants"][0]["items"][0]["name"] == "Chicken Biryani"
        assert cart_data["restaurants"][0]["items"][0]["quantity"] == 2

    def test_finalize_merges_multiple_restaurants_into_pending_cart(self, client):
        owner_token = _owner_token(client, "multi_finalize_owner@test.com")
        restaurant_one = create_test_restaurant(client, owner_token, name="Anjappar", city="Chicago")
        category_one = create_test_category(client, owner_token, restaurant_one.json()["id"], name="Main")
        create_test_item(client, owner_token, category_one.json()["id"], name="Parotta", price_cents=499)

        restaurant_two = create_test_restaurant(client, owner_token, name="Chettinad House", city="Chicago")
        category_two = create_test_category(client, owner_token, restaurant_two.json()["id"], name="Main")
        create_test_item(client, owner_token, category_two.json()["id"], name="Mutton Biryani", price_cents=1899)

        customer = register_user(client, email="multi_finalize_customer@test.com", password="password123")
        token = customer.json()["access_token"]

        session = client.post("/api/call-order/session", json={"language": "en-IN"}).json()
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add parotta"},
        )
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "yes"},
        )
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "add mutton biryani"},
        )
        client.post(
            "/api/call-order/turn",
            json={"session_id": session["session_id"], "transcript": "yes"},
        )

        finalize = client.post(
            f"/api/call-order/session/{session['session_id']}/finalize",
            headers=get_auth_header(token),
        )
        assert finalize.status_code == 200
        assert finalize.json()["materialized_restaurant_count"] == 2

        cart = client.get("/cart", headers=get_auth_header(token))
        assert cart.status_code == 200
        cart_data = cart.json()
        assert len(cart_data["restaurants"]) == 2
        assert sorted(group["restaurant_name"] for group in cart_data["restaurants"]) == ["Anjappar", "Chettinad House"]
