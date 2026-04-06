from __future__ import annotations

import httpx
import json
import logging
import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from . import crud, models
from .auth import get_current_user
from .call_order import (
    _add_to_draft_cart,
    _assistant_greeting,
    _finalize_draft_cart,
    _get_session_record,
    _normalize_language,
    _persist_session,
    _remove_from_draft_cart,
    _session_from_record,
    _session_snapshot,
    _summarize_cart,
)
from .config import settings
from .db import get_db
from . import payments

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/call-order/realtime", tags=["call-order-realtime"])


class RealtimeSessionBootstrapIn(BaseModel):
    language: str = Field(default="en-IN")
    session_id: str | None = None


class RealtimeRestaurantToolIn(BaseModel):
    session_id: str
    query: str = Field(min_length=1)
    lat: float | None = None
    lng: float | None = None
    radius_miles: float | None = None


class RealtimeRestaurantBrowseToolIn(BaseModel):
    session_id: str
    query: str | None = None
    limit: int = Field(default=8, ge=1, le=20)
    lat: float | None = None
    lng: float | None = None
    radius_miles: float | None = None


class RealtimeMenuToolIn(BaseModel):
    session_id: str
    restaurant_id: int | None = None
    restaurant_name: str | None = None
    query: str | None = None
    known_restaurant_ids: list[int] | None = None


class RealtimeDraftItemToolIn(BaseModel):
    session_id: str
    item_id: int
    quantity: int = Field(default=1, ge=1, le=20)
    item_name: str | None = None
    restaurant_id: int | None = None

    @field_validator("item_id", mode="before")
    @classmethod
    def coerce_item_id(cls, v):
        """LLMs sometimes send item_id as float (e.g. 42.0). Coerce gracefully."""
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return int(v)


class RealtimeStartCheckoutIn(BaseModel):
    session_id: str


def _create_call_session(db: Session, language: str) -> dict:
    greeting = _assistant_greeting(language)
    session = {
        "id": __import__("uuid").uuid4().hex,
        "language": language,
        "state": "ready",
        "created_at": datetime.utcnow().isoformat(),
        "history": [{"role": "assistant", "text": greeting}],
        "last_assistant_reply": greeting,
        "selected_restaurant": None,
        "selected_item": None,
        "draft_cart": [],
        "pending_action": None,
    }
    return _persist_session(db, session)


def _get_or_create_call_session(db: Session, session_id: str | None, language: str) -> dict:
    if session_id:
        record = _get_session_record(db, session_id)
        if not record:
            raise HTTPException(status_code=404, detail="Call session not found")
        return _session_from_record(record)
    return _create_call_session(db, language)


def _provider_config() -> dict:
    provider_name = str(settings.ai_call_provider or "vapi").strip().lower() or "vapi"
    assistant_id_en = settings.ai_call_provider_assistant_id_en or settings.ai_call_provider_assistant_id
    assistant_id_ta = settings.ai_call_provider_assistant_id_ta or settings.ai_call_provider_assistant_id
    agent_id_en = settings.ai_call_provider_agent_id_en or settings.ai_call_provider_agent_id
    agent_id_ta = settings.ai_call_provider_agent_id_ta or settings.ai_call_provider_agent_id
    missing_fields: list[str] = []

    if provider_name == "retell":
        if not agent_id_en:
            missing_fields.append("agent_id")
    else:
        if not settings.ai_call_provider_public_key:
            missing_fields.append("public_key")
        if not assistant_id_en:
            missing_fields.append("assistant_id")

    result = {
        "name": provider_name,
        "enabled": bool(settings.ai_call_realtime_enabled),
        "public_key": settings.ai_call_provider_public_key,
        "assistant_id": settings.ai_call_provider_assistant_id,
        "assistant_ids": {
            "en-IN": assistant_id_en,
            "ta-IN": assistant_id_ta,
        },
        "agent_id": settings.ai_call_provider_agent_id,
        "agent_ids": {
            "en-IN": agent_id_en,
            "ta-IN": agent_id_ta,
        },
        "phone_number_id": settings.ai_call_provider_phone_number_id,
        "transport": "managed-provider",
        "configured": len(missing_fields) == 0,
        "missing_fields": missing_fields,
        "server_url": settings.retell_server_url if provider_name == "retell" else settings.vapi_server_url,
    }

    # When primary is Retell, expose Vapi as fallback so the frontend can
    # attempt Vapi before dropping to local-only voice mode.
    if provider_name == "retell" and settings.ai_call_provider_public_key and assistant_id_en:
        result["fallback"] = {
            "name": "vapi",
            "public_key": settings.ai_call_provider_public_key,
            "assistant_id": settings.ai_call_provider_assistant_id,
            "assistant_ids": {
                "en-IN": assistant_id_en,
                "ta-IN": assistant_id_ta,
            },
            "server_url": settings.vapi_server_url,
        }

    return result


def _tool_catalog() -> list[dict]:
    return [
        {
            "name": "list_restaurants",
            "description": "Return available restaurants from the live database for broad restaurant availability questions.",
            "endpoint": "/api/call-order/realtime/tools/list-restaurants",
        },
        {
            "name": "find_restaurants",
            "description": "Find likely restaurant matches from a spoken query.",
            "endpoint": "/api/call-order/realtime/tools/find-restaurants",
        },
        {
            "name": "get_restaurant_menu",
            "description": "Return menu categories and likely items for a restaurant.",
            "endpoint": "/api/call-order/realtime/tools/menu",
        },
        {
            "name": "get_draft_summary",
            "description": "Return the current AI Call draft cart summary.",
            "endpoint": "/api/call-order/realtime/tools/draft-summary/{session_id}",
        },
        {
            "name": "add_draft_item",
            "description": "Add a confirmed item to the AI Call draft cart.",
            "endpoint": "/api/call-order/realtime/tools/add-item",
        },
        {
            "name": "remove_draft_item",
            "description": "Remove an item from the AI Call draft cart.",
            "endpoint": "/api/call-order/realtime/tools/remove-item",
        },
        {
            "name": "finalize_draft_to_cart",
            "description": "Move the AI Call draft into the authenticated application cart.",
            "endpoint": "/api/call-order/session/{session_id}/finalize",
        },
        {
            "name": "start_checkout",
            "description": "Materialize the AI Call draft if needed and create an application checkout session.",
            "endpoint": "/api/call-order/realtime/tools/start-checkout",
        },
    ]


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _has_menu(db: Session, restaurant_id: int) -> bool:
    """Return True if the restaurant has at least one menu category with items."""
    cat = db.query(models.MenuCategory.id).filter(models.MenuCategory.restaurant_id == restaurant_id).first()
    return cat is not None


def _filter_by_location_and_menu(db: Session, restaurants, lat: float | None, lng: float | None, radius_miles: float | None):
    """Filter restaurants: must have a menu, and optionally within radius."""
    result = []
    for r in restaurants:
        if not _has_menu(db, r.id if hasattr(r, 'id') else r.get('id')):
            continue
        if lat is not None and lng is not None and radius_miles is not None:
            r_lat = r.latitude if hasattr(r, 'latitude') else None
            r_lng = r.longitude if hasattr(r, 'longitude') else None
            if r_lat and r_lng and not (r_lat == 0.0 and r_lng == 0.0):
                dist = _haversine_miles(lat, lng, float(r_lat), float(r_lng))
                if dist > radius_miles:
                    continue
            # Restaurants without coords pass through (not excluded)
        result.append(r)
    return result


def _item_payload(item: models.MenuItem, restaurant: models.Restaurant, category: models.MenuCategory) -> dict:
    return {
        "type": "item",
        "id": item.id,
        "name": item.name,
        "price_cents": item.price_cents,
        "restaurant_id": restaurant.id,
        "restaurant_name": restaurant.name,
        "category_id": category.id,
        "category_name": category.name,
    }


def _get_menu_item_context(db: Session, item_id: int) -> tuple[models.MenuItem, models.Restaurant, models.MenuCategory]:
    item = db.query(models.MenuItem).filter(models.MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    category = db.query(models.MenuCategory).filter(models.MenuCategory.id == item.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Menu category not found")
    restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == category.restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return item, restaurant, category


@router.post("/session")
def bootstrap_ai_call_realtime_session(payload: RealtimeSessionBootstrapIn, db: Session = Depends(get_db)):
    language = _normalize_language(payload.language)
    session = _get_or_create_call_session(db, payload.session_id, language)
    snapshot = _session_snapshot(session)
    snapshot["realtime"] = {
        "enabled": bool(settings.ai_call_realtime_enabled),
        "provider": _provider_config(),
        "tools": _tool_catalog(),
    }
    return snapshot


@router.post("/tools/find-restaurants")
def realtime_find_restaurants(payload: RealtimeRestaurantToolIn, db: Session = Depends(get_db)):
    session = _get_or_create_call_session(db, payload.session_id, "en-IN")
    query = payload.query.strip().lower()
    restaurants = crud.list_restaurants(db)
    filtered = []
    for r in restaurants:
        if not _has_menu(db, r.id):
            continue
        if query not in r.name.lower():
            continue
        if payload.lat is not None and payload.lng is not None and payload.radius_miles is not None:
            if r.latitude and r.longitude and not (r.latitude == 0.0 and r.longitude == 0.0):
                dist = _haversine_miles(payload.lat, payload.lng, float(r.latitude), float(r.longitude))
                if dist > payload.radius_miles:
                    continue
        filtered.append({"id": r.id, "name": r.name})
    if not filtered:
        # No match — return all restaurants with menus
        filtered = [{"id": r.id, "name": r.name} for r in restaurants if _has_menu(db, r.id)]
    return {
        "session_id": session["id"],
        "query": payload.query,
        "restaurants": filtered[:5],
    }


@router.post("/tools/list-restaurants")
def realtime_list_restaurants(payload: RealtimeRestaurantBrowseToolIn, db: Session = Depends(get_db)):
    session = _get_or_create_call_session(db, payload.session_id, "en-IN")
    restaurants = crud.list_restaurants(db)
    restaurants = _filter_by_location_and_menu(db, restaurants, payload.lat, payload.lng, payload.radius_miles)
    query = (payload.query or "").strip().lower()
    filtered = [
        restaurant for restaurant in restaurants
        if not query or query in restaurant.name.lower() or query in (restaurant.city or "").lower()
    ]
    if query and not filtered:
        filtered = restaurants
    filtered.sort(key=lambda restaurant: restaurant.name.lower())
    return {
        "session_id": session["id"],
        "query": payload.query or "",
        "restaurants": [
            {
                "id": restaurant.id,
                "name": restaurant.name,
                "city": restaurant.city,
                "type": "restaurant",
            }
            for restaurant in filtered[: payload.limit]
        ],
        "total_matches": len(filtered),
    }


@router.post("/tools/menu")
def realtime_get_restaurant_menu(payload: RealtimeMenuToolIn, db: Session = Depends(get_db)):
    session = _get_or_create_call_session(db, payload.session_id, "en-IN")
    restaurant = None
    if payload.restaurant_id is not None:
        restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == payload.restaurant_id).first()

    if not restaurant and payload.restaurant_name:
        name_lower = payload.restaurant_name.strip().lower()
        for r in crud.list_restaurants(db):
            if name_lower in r.name.lower() or r.name.lower() in name_lower:
                restaurant = r
                break

    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    categories_payload: list[dict] = []
    for category in crud.list_categories(db, restaurant.id):
        items = crud.list_items(db, category.id)
        categories_payload.append(
            {
                "id": category.id,
                "name": category.name,
                "items": [
                    {"id": item.id, "name": item.name, "price_cents": item.price_cents}
                    for item in items
                ],
            }
        )

    if not categories_payload:
        return {
            "status": "FAILED",
            "error": "Menu empty",
            "instruction": f"Tell the user 'I am sorry, but {restaurant.name} does not have any menu items available at the moment. Would you like to try a different restaurant?'",
            "restaurant": {"id": restaurant.id, "name": restaurant.name},
            "session_id": session["id"]
        }

    return {
        "session_id": session["id"],
        "restaurant": {"id": restaurant.id, "name": restaurant.name},
        "categories": categories_payload,
    }


@router.get("/tools/draft-summary/{session_id}")
def realtime_draft_summary(session_id: str, db: Session = Depends(get_db)):
    session = _get_or_create_call_session(db, session_id, "en-IN")
    return {
        "session_id": session["id"],
        "summary": _summarize_cart(session),
        "draft": _session_snapshot(session),
    }


@router.post("/tools/add-item")
def realtime_add_item(payload: RealtimeDraftItemToolIn, db: Session = Depends(get_db)):
    session = _get_or_create_call_session(db, payload.session_id, "en-IN")
    item, restaurant, category = _get_menu_item_context(db, payload.item_id)
    candidate = _item_payload(item, restaurant, category)
    _add_to_draft_cart(session, candidate, payload.quantity)
    session["selected_restaurant"] = {"id": restaurant.id, "name": restaurant.name, "type": "restaurant", "score": 1.0}
    session["selected_item"] = candidate
    session["pending_action"] = None
    session["last_assistant_reply"] = f"Added {payload.quantity} {item.name} to your draft order."
    persisted = _persist_session(db, session)
    return {
        "session_id": session["id"],
        "summary": _summarize_cart(persisted),
        "draft": _session_snapshot(persisted),
    }


@router.post("/tools/remove-item")
def realtime_remove_item(payload: RealtimeDraftItemToolIn, db: Session = Depends(get_db)):
    session = _get_or_create_call_session(db, payload.session_id, "en-IN")
    item, restaurant, category = _get_menu_item_context(db, payload.item_id)
    candidate = _item_payload(item, restaurant, category)
    removed = _remove_from_draft_cart(session, candidate, payload.quantity)
    if not removed:
        raise HTTPException(status_code=404, detail="Item not found in draft order")
    session["selected_restaurant"] = {"id": restaurant.id, "name": restaurant.name, "type": "restaurant", "score": 1.0}
    session["selected_item"] = candidate
    session["pending_action"] = None
    session["last_assistant_reply"] = f"Removed {payload.quantity} {item.name} from your draft order."
    persisted = _persist_session(db, session)
    return {
        "session_id": session["id"],
        "summary": _summarize_cart(persisted),
        "draft": _session_snapshot(persisted),
    }


@router.post("/tools/start-checkout")
def realtime_start_checkout(
    payload: RealtimeStartCheckoutIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = _get_or_create_call_session(db, payload.session_id, "en-IN")

    materialized_item_count = 0
    materialized_restaurant_count = 0
    if session.get("draft_cart"):
        materialized_item_count, materialized_restaurant_count = _finalize_draft_cart(session, db, current_user.id)
        session["draft_cart"] = []
        session["pending_action"] = None
        session["last_assistant_reply"] = (
            f"Moved {materialized_item_count} item{'s' if materialized_item_count != 1 else ''} into your cart and started checkout."
        )
        session["history"].append({"role": "assistant", "text": session["last_assistant_reply"]})
        session = _persist_session(db, session)

    checkout = payments.create_order_checkout(db, current_user)
    return {
        "session_id": session["id"],
        "checkout": checkout,
        "draft": _session_snapshot(session),
        "materialized_item_count": materialized_item_count,
        "materialized_restaurant_count": materialized_restaurant_count,
    }


@router.get("/provider-config")
def get_ai_call_provider_config():
    return {
        "enabled": bool(settings.ai_call_realtime_enabled),
        "provider": _provider_config(),
        "tools": _tool_catalog(),
    }


# ---------------------------------------------------------------------------
# Vapi server-side webhook – receives tool-call requests from Vapi's server
# and returns results so the model sees them immediately.
# Docs: https://docs.vapi.ai/tools/custom-tools
# ---------------------------------------------------------------------------

def _execute_realtime_tool(
    name: str,
    arguments: dict,
    session_id: str,
    db: Session,
) -> dict:
    """Dispatch a realtime provider tool call to the matching backend handler."""
    if name == "list_restaurants":
        session = _get_or_create_call_session(db, session_id, "en-IN")
        restaurants = crud.list_restaurants(db)
        query = str(arguments.get("query") or "").strip().lower()
        limit = int(arguments.get("limit") or 8)
        filtered = [
            r for r in restaurants
            if not query
            or query in r.name.lower()
            or query in (r.city or "").lower()
        ]
        if query and not filtered:
            filtered = restaurants
        filtered.sort(key=lambda r: r.name.lower())
        return {
            "restaurants": [
                {"id": r.id, "name": r.name}
                for r in filtered[:limit]
            ],
            "total": len(filtered),
        }

    if name == "find_restaurants":
        _get_or_create_call_session(db, session_id, "en-IN")
        query = str(arguments.get("query") or "").strip().lower()
        restaurants = crud.list_restaurants(db)
        matches = [
            {"id": r.id, "name": r.name}
            for r in restaurants
            if query in r.name.lower()
        ]
        if not matches:
            matches = [{"id": r.id, "name": r.name} for r in restaurants]
        return {
            "query": query,
            "restaurants": matches[:5],
        }

    if name == "get_restaurant_menu":
        _get_or_create_call_session(db, session_id, "en-IN")
        restaurant_id = arguments.get("restaurant_id")
        restaurant_name = str(arguments.get("restaurant_name") or "").strip()
        restaurant = None
        if restaurant_id is not None:
            try:
                restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == int(restaurant_id)).first()
            except (ValueError, TypeError):
                pass
        if not restaurant and restaurant_name:
            # Simple case-insensitive name match
            name_lower = restaurant_name.lower()
            for r in crud.list_restaurants(db):
                if name_lower in r.name.lower() or r.name.lower() in name_lower:
                    restaurant = r
                    break
        if not restaurant:
            return {
                "error": "Restaurant not found",
                "instruction": "Tell the user you could not find that restaurant. Ask them to say 'list restaurants' to see available options.",
            }
        categories_payload: list[dict] = []
        for cat in crud.list_categories(db, restaurant.id):
            items = crud.list_items(db, cat.id)
            categories_payload.append({
                "id": cat.id,
                "name": cat.name,
                "items": [{"id": i.id, "name": i.name, "price_cents": i.price_cents} for i in items],
            })
        if not categories_payload:
            return {
                "status": "FAILED",
                "error": f"Menu empty for {restaurant.name}",
                "instruction": f"Tell the user '{restaurant.name}' does not have any menu items available. Suggest trying a different restaurant.",
            }
        return {
            "restaurant": {"id": restaurant.id, "name": restaurant.name},
            "categories": categories_payload,
        }

    if name == "get_draft_summary":
        session = _get_or_create_call_session(db, session_id, "en-IN")
        return {"summary": _summarize_cart(session)}

    if name == "add_draft_item":
        session = _get_or_create_call_session(db, session_id, "en-IN")
        item_id = int(arguments.get("item_id", 0))
        quantity = min(20, max(1, int(arguments.get("quantity") or 1)))
        item, restaurant, category = _get_menu_item_context(db, item_id)
        candidate = _item_payload(item, restaurant, category)
        _add_to_draft_cart(session, candidate, quantity)
        session["selected_restaurant"] = {"id": restaurant.id, "name": restaurant.name, "type": "restaurant", "score": 1.0}
        session["selected_item"] = candidate
        session["pending_action"] = None
        session["last_assistant_reply"] = f"Added {quantity} {item.name} to your draft order."
        _persist_session(db, session)
        return {"summary": _summarize_cart(session), "added": item.name, "quantity": quantity}

    if name == "remove_draft_item":
        session = _get_or_create_call_session(db, session_id, "en-IN")
        item_id = int(arguments.get("item_id", 0))
        quantity = min(20, max(1, int(arguments.get("quantity") or 1)))
        item, restaurant, category = _get_menu_item_context(db, item_id)
        candidate = _item_payload(item, restaurant, category)
        removed = _remove_from_draft_cart(session, candidate, quantity)
        if not removed:
            return {"error": "Item not found in draft order"}
        _persist_session(db, session)
        return {"summary": _summarize_cart(session), "removed": item.name, "quantity": quantity}

    if name in ("finalize_draft_to_cart", "start_checkout"):
        return {"message": "Please use the on-screen button to move your order to cart and check out."}

    return {"error": f"Unknown tool: {name}"}


@router.post("/vapi-webhook")
async def vapi_tool_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle incoming Vapi server-side tool call webhook requests.

    Vapi sends POST {message: {type: "tool-calls", toolCallList: [...], assistant: {...}}}
    We respond with {results: [{toolCallId, result}]}.
    """
    body = await request.json()
    message = body.get("message", {})

    # Verify webhook secret if configured
    if settings.vapi_webhook_secret:
        header_secret = request.headers.get("x-vapi-secret", "")
        if header_secret != settings.vapi_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    message_type = message.get("type", "")

    # Only handle tool-calls; acknowledge other message types
    if message_type != "tool-calls":
        return {"ok": True}

    tool_call_list = message.get("toolCallList", [])
    assistant_metadata = message.get("assistant", {}).get("metadata", {})
    session_id = (
        assistant_metadata.get("sessionId")
        or assistant_metadata.get("session_id")
        or ""
    )

    if not session_id:
        logger.warning("Vapi webhook: no session_id in assistant metadata")
        return {"results": [{"toolCallId": tc.get("id", ""), "error": "Missing session_id"} for tc in tool_call_list]}

    results = []
    for tc in tool_call_list:
        tc_id = tc.get("id", "")
        tc_name = tc.get("name", "") or tc.get("function", {}).get("name", "")
        tc_args = tc.get("arguments", {})
        if isinstance(tc_args, str):
            try:
                tc_args = json.loads(tc_args)
            except (json.JSONDecodeError, TypeError):
                tc_args = {}
        if not isinstance(tc_args, dict):
            tc_args = {}

        try:
            result = _execute_realtime_tool(tc_name, tc_args, session_id, db)
            results.append({"toolCallId": tc_id, "result": json.dumps(result)})
        except HTTPException as exc:
            results.append({"toolCallId": tc_id, "result": json.dumps({
                "status": "FAILED",
                "error": exc.detail,
                "instruction": "This action FAILED. Tell the caller it did not work and why. Do NOT say it succeeded.",
            })})
        except Exception as exc:
            logger.exception("Vapi tool %s failed", tc_name)
            results.append({"toolCallId": tc_id, "result": json.dumps({
                "status": "FAILED",
                "error": str(exc),
                "instruction": "This action FAILED. Tell the caller it did not work and why. Do NOT say it succeeded.",
            })})

    return {"results": results}


def _normalize_webhook_tool_calls(body: dict, source: str) -> tuple[list[dict], str]:
    """Extract tool call list and session id from provider webhook payloads."""
    if source == "vapi":
        logger.info("[_normalize_webhook_tool_calls] Vapi body: %s", body)
        message = body.get("message", {})
        tool_calls = message.get("toolCallList", [])
        assistant_metadata = message.get("assistant", {}).get("metadata", {})
        session_id = (
            assistant_metadata.get("sessionId")
            or assistant_metadata.get("session_id")
            or ""
        )
        return tool_calls, str(session_id)

    # Retell payload variations: event/object wrappers or direct function payloads.
    payload = body.get("data", body)
    logger.info("[_normalize_webhook_tool_calls] Retell payload: %s", payload)
    if not isinstance(payload, dict):
        return [], ""

    # --- Extract session_id from multiple possible locations ---
    call_info = payload.get("call", {})
    if not isinstance(call_info, dict):
        call_info = {}
    call_metadata = call_info.get("metadata", {})
    if not isinstance(call_metadata, dict):
        call_metadata = {}
    session_meta = payload.get("session", {}) if isinstance(payload.get("session"), dict) else {}
    top_metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    assistant = payload.get("assistant", {}) if isinstance(payload.get("assistant"), dict) else {}
    assistant_metadata = assistant.get("metadata", {}) if isinstance(assistant, dict) else {}
    session_id = (
        call_metadata.get("sessionId")
        or call_metadata.get("session_id")
        or top_metadata.get("sessionId")
        or top_metadata.get("session_id")
        or session_meta.get("id")
        or session_meta.get("session_id")
        or assistant_metadata.get("sessionId")
        or assistant_metadata.get("session_id")
        or payload.get("session_id")
        or ""
    )

    tool_calls: list[dict] = []
    candidates = []
    candidates.extend(payload.get("toolCallList") or [])
    candidates.extend(payload.get("tool_calls") or [])
    candidates.extend(payload.get("toolCalls") or [])

    function_call = payload.get("function_call")
    if isinstance(function_call, dict):
        candidates.append(function_call)

    tool_call = payload.get("tool_call")
    if isinstance(tool_call, dict):
        candidates.append(tool_call)

    # Retell Custom Function format: { args: {...}, call: {...} }
    # The tool name is typically passed as a field or derived from the URL.
    retell_args = payload.get("args")
    retell_fn_name = payload.get("name") or payload.get("function_name") or payload.get("tool_name") or ""
    if isinstance(retell_args, dict) and retell_fn_name:
        candidates.append({"name": retell_fn_name, "arguments": retell_args, "id": call_info.get("call_id", "retell-auto")})

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        tc_id = candidate.get("id") or candidate.get("tool_call_id") or candidate.get("call_id") or ""
        fn_name = candidate.get("name") or candidate.get("function", {}).get("name") or candidate.get("tool_name") or ""
        fn_args = candidate.get("arguments") or candidate.get("args") or candidate.get("function", {}).get("arguments") or {}
        tool_calls.append({"id": tc_id, "name": fn_name, "arguments": fn_args})

    logger.info("[_normalize_webhook_tool_calls] Extracted tool_calls: %s, session_id: %s", tool_calls, session_id)
    return tool_calls, str(session_id)


def _execute_webhook_tool_calls(
    tool_call_list: list[dict],
    session_id: str,
    db: Session,
    provider_name: str,
) -> list[dict]:
    results = []
    for tc in tool_call_list:
        tc_id = tc.get("id", "")
        tc_name = tc.get("name", "") or tc.get("function", {}).get("name", "")
        tc_args = tc.get("arguments", {})
        if isinstance(tc_args, str):
            try:
                tc_args = json.loads(tc_args)
            except (json.JSONDecodeError, TypeError):
                tc_args = {}
        if not isinstance(tc_args, dict):
            tc_args = {}

        try:
            result = _execute_realtime_tool(tc_name, tc_args, session_id, db)
            results.append({"toolCallId": tc_id, "result": json.dumps(result)})
        except HTTPException as exc:
            results.append({
                "toolCallId": tc_id,
                "result": json.dumps({
                    "status": "FAILED",
                    "error": exc.detail,
                    "instruction": "This action FAILED. Tell the caller it did not work and why. Do NOT say it succeeded.",
                }),
            })
        except Exception as exc:
            logger.exception("%s tool %s failed", provider_name, tc_name)
            results.append({
                "toolCallId": tc_id,
                "result": json.dumps({
                    "status": "FAILED",
                    "error": str(exc),
                    "instruction": "This action FAILED. Tell the caller it did not work and why. Do NOT say it succeeded.",
                }),
            })
    return results


@router.post("/create-web-call")
def create_retell_web_call(payload: dict, db: Session = Depends(get_db)):
    """Create a Retell web call and return the access_token for the frontend SDK."""
    provider = _provider_config()
    if provider["name"] != "retell":
        raise HTTPException(status_code=400, detail="Provider is not Retell; web-call creation not applicable.")
    if not settings.retell_api_key:
        raise HTTPException(status_code=500, detail="RETELL_API_KEY is not configured.")

    language = _normalize_language(payload.get("language", "en-IN"))
    agent_id = provider["agent_ids"].get(language) or provider["agent_id"]
    if not agent_id:
        raise HTTPException(status_code=500, detail=f"No Retell agent configured for language {language}.")

    session_id = payload.get("session_id")
    metadata = payload.get("metadata", {})
    if session_id:
        metadata["session_id"] = session_id

    # Build language-specific instruction injected via Retell dynamic variables.
    # The Retell agent prompt must contain {{language_instruction}} placeholder.
    if language == "ta-IN":
        language_instruction = (
            "Respond in Tanglish using ONLY English/Latin letters — the way Tamil "
            "people casually speak mixing Tamil and English. Write Tamil words in "
            "English letters (romanized), for example: 'Enna saapidanum?', "
            "'Romba nalla irukku', 'Oru nimisham', 'Seri podlama?', 'Add panniduren'. "
            "NEVER use Tamil script (Unicode). NEVER use Hindi or Telugu. "
            "Use English for food names, restaurant names, prices, and action words. "
            "Keep it short, friendly, and natural like a local conversation."
        )
    else:
        language_instruction = "Respond in English suitable for Indian restaurant ordering calls."

    retell_payload = {
        "agent_id": agent_id,
        "retell_llm_dynamic_variables": {
            "language_instruction": language_instruction,
        },
    }
    if metadata:
        retell_payload["metadata"] = metadata
    retell_webhook = payload.get("webhook_url")
    if retell_webhook:
        retell_payload["webhook_url"] = retell_webhook

    try:
        resp = httpx.post(
            "https://api.retellai.com/v2/create-web-call",
            json=retell_payload,
            headers={
                "Authorization": f"Bearer {settings.retell_api_key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Retell create-web-call failed: %s %s", exc.response.status_code, exc.response.text)
        raise HTTPException(status_code=502, detail="Failed to create Retell web call.") from exc
    except httpx.RequestError as exc:
        logger.error("Retell create-web-call request error: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach Retell API.") from exc

    data = resp.json()
    return {
        "access_token": data.get("access_token"),
        "call_id": data.get("call_id"),
        "agent_id": agent_id,
    }


@router.post("/retell-tool/{tool_name}")
async def retell_custom_function_handler(tool_name: str, request: Request, db: Session = Depends(get_db)):
    """Handle Retell Custom Function webhook calls.

    Each Retell Custom Function is configured in the Retell dashboard with a URL
    pointing to this endpoint, e.g.:
        https://<backend>/api/call-order/realtime/retell-tool/list_restaurants

    Retell sends: { args: {...}, call: { call_id, agent_id, metadata: {sessionId} } }
    We return a plain JSON result that Retell feeds back to the LLM.
    """
    body = await request.json()
    logger.info("[Retell Tool] %s called with: %s", tool_name, body)

    if settings.retell_webhook_secret:
        header_secret = (
            request.headers.get("x-retell-signature", "")
            or request.headers.get("x-retell-secret", "")
        )
        if header_secret and header_secret != settings.retell_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Extract args from Retell's Custom Function format
    args = body.get("args", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            args = {}
    if not isinstance(args, dict):
        args = {}

    # Extract session_id from call.metadata
    call_info = body.get("call", {})
    if not isinstance(call_info, dict):
        call_info = {}
    metadata = call_info.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    session_id = (
        metadata.get("sessionId")
        or metadata.get("session_id")
        or args.pop("session_id", None)
        or ""
    )

    if not session_id:
        logger.warning("[Retell Tool] No session_id in metadata for %s. metadata=%s", tool_name, metadata)
        return {
            "error": "Missing session_id. Ensure the web call was created with sessionId in metadata.",
            "instruction": "Tell the user there was a technical issue connecting to the ordering system.",
        }

    try:
        result = _execute_realtime_tool(tool_name, args, str(session_id), db)
        logger.info("[Retell Tool] %s succeeded, keys: %s", tool_name, list(result.keys()) if isinstance(result, dict) else type(result))
        return result
    except HTTPException as exc:
        logger.warning("[Retell Tool] %s HTTPException: %s", tool_name, exc.detail)
        return {
            "status": "FAILED",
            "error": exc.detail,
            "instruction": "This action FAILED. Tell the caller it did not work and why.",
        }
    except Exception as exc:
        logger.exception("[Retell Tool] %s failed", tool_name)
        return {
            "status": "FAILED",
            "error": str(exc),
            "instruction": "This action FAILED. Tell the caller it did not work and why.",
        }


@router.post("/retell-webhook")
async def retell_tool_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle incoming Retell tool-call style webhook requests.

    The payload can vary by Retell event type; this endpoint normalizes known
    tool-call envelopes into the same internal execution path as Vapi.
    """
    body = await request.json()
    logger.info("[Retell Webhook] Incoming payload: %s", body)

    if settings.retell_webhook_secret:
        header_secret = request.headers.get("x-retell-signature", "") or request.headers.get("x-retell-secret", "")
        if header_secret != settings.retell_webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    tool_call_list, session_id = _normalize_webhook_tool_calls(body, source="retell")
    logger.info("[Retell Webhook] Normalized tool_call_list: %s, session_id: %s", tool_call_list, session_id)
    if not tool_call_list:
        return {"ok": True}
    if not session_id:
        logger.warning("Retell webhook: no session_id in payload")
        return {
            "results": [{"toolCallId": tc.get("id", ""), "error": "Missing session_id"} for tc in tool_call_list],
        }

    results = _execute_webhook_tool_calls(tool_call_list, session_id, db, provider_name="Retell")
    # Return both generic and Retell-friendly keys for compatibility.
    return {
        "results": results,
        "tool_results": [
            {
                "tool_call_id": result.get("toolCallId", ""),
                "result": result.get("result", "{}"),
            }
            for result in results
        ],
    }
