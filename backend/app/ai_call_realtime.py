from __future__ import annotations

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
    _item_candidates,
    _normalize_spoken_text,
    _restaurant_request_phrase,
    _normalize_language,
    _persist_session,
    _remove_from_draft_cart,
    _restaurant_candidates,
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
    assistant_id_en = settings.ai_call_provider_assistant_id_en or settings.ai_call_provider_assistant_id
    assistant_id_ta = settings.ai_call_provider_assistant_id_ta or settings.ai_call_provider_assistant_id
    missing_fields: list[str] = []
    if not settings.ai_call_provider_public_key:
        missing_fields.append("public_key")
    if not assistant_id_en:
        missing_fields.append("assistant_id")
    return {
        "name": settings.ai_call_provider,
        "enabled": bool(settings.ai_call_realtime_enabled),
        "public_key": settings.ai_call_provider_public_key,
        "assistant_id": settings.ai_call_provider_assistant_id,
        "assistant_ids": {
            "en-IN": assistant_id_en,
            "ta-IN": assistant_id_ta,
        },
        "phone_number_id": settings.ai_call_provider_phone_number_id,
        "transport": "managed-provider",
        "configured": len(missing_fields) == 0,
        "missing_fields": missing_fields,
        "server_url": settings.vapi_server_url,
    }


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


def _resolve_item_with_fallback(
    db: Session,
    item_id: int,
    item_name: str | None = None,
    restaurant_id: int | None = None,
) -> tuple[models.MenuItem, models.Restaurant, models.MenuCategory]:
    """Look up a menu item by ID, but auto-correct using name-based search if the
    resolved item doesn't match the expected name or restaurant.  This handles
    the common case where the LLM hallucinates or confuses item IDs."""
    import logging
    logger = logging.getLogger(__name__)

    # Try the direct ID lookup first
    try:
        item, restaurant, category = _get_menu_item_context(db, item_id)
    except HTTPException:
        item, restaurant, category = None, None, None

    # Check if the resolved item matches expectations
    needs_correction = False
    if item is None:
        needs_correction = True
    elif restaurant_id is not None and category.restaurant_id != restaurant_id:
        logger.warning(
            "Item ID %d belongs to restaurant %d (%s) but caller expected restaurant %d – attempting name-based correction",
            item_id, category.restaurant_id, restaurant.name, restaurant_id,
        )
        needs_correction = True
    elif item_name and item_name.strip():
        # Fuzzy check: if the resolved item name is clearly different from what was asked
        resolved_lower = item.name.lower().strip()
        expected_lower = item_name.lower().strip()
        if resolved_lower != expected_lower and expected_lower not in resolved_lower and resolved_lower not in expected_lower:
            logger.warning(
                "Item ID %d resolved to '%s' but caller expected '%s' – attempting name-based correction",
                item_id, item.name, item_name,
            )
            needs_correction = True

    if needs_correction and item_name and item_name.strip():
        # Use the existing fuzzy search to find the right item
        candidates = _item_candidates(db, item_name, restaurant_id)
        if not candidates and restaurant_id is not None:
            # If the LLM hallucinated the restaurant_id too, search globally!
            candidates = _item_candidates(db, item_name, None)
            
        if candidates:
            best = candidates[0]
            logger.info(
                "Name-based correction: '%s' → item %d '%s' (score %.2f) in restaurant %d",
                item_name, best["id"], best["name"], best["score"], best["restaurant_id"],
            )
            return _get_menu_item_context(db, best["id"])

    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Menu item not found for id={item_id}" + (f" name='{item_name}'" if item_name else ""),
        )

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
    matches = _restaurant_candidates(db, payload.query)
    # Filter: only restaurants with menus and within radius
    filtered = []
    for m in matches:
        r = db.query(models.Restaurant).filter(models.Restaurant.id == m["id"]).first()
        if not r or not _has_menu(db, r.id):
            continue
        if payload.lat is not None and payload.lng is not None and payload.radius_miles is not None:
            if r.latitude and r.longitude and not (r.latitude == 0.0 and r.longitude == 0.0):
                dist = _haversine_miles(payload.lat, payload.lng, float(r.latitude), float(r.longitude))
                if dist > payload.radius_miles:
                    continue
        filtered.append(m)
    return {
        "session_id": session["id"],
        "query": payload.query,
        "restaurants": filtered,
    }


@router.post("/tools/list-restaurants")
def realtime_list_restaurants(payload: RealtimeRestaurantBrowseToolIn, db: Session = Depends(get_db)):
    session = _get_or_create_call_session(db, payload.session_id, "en-IN")
    restaurants = crud.list_restaurants(db)
    # Filter by location radius and must have menu
    restaurants = _filter_by_location_and_menu(db, restaurants, payload.lat, payload.lng, payload.radius_miles)
    normalized_query = _restaurant_request_phrase(payload.query or "")
    if not normalized_query:
        normalized_query = _normalize_spoken_text(payload.query or "")
    filtered = [
        restaurant for restaurant in restaurants
        if not normalized_query or normalized_query in restaurant.name.lower() or normalized_query in (restaurant.city or "").lower()
    ]
    if normalized_query and not filtered:
        filtered = restaurants
    filtered.sort(key=lambda restaurant: restaurant.name.lower())
    return {
        "session_id": session["id"],
        "query": payload.query or "",
        "normalized_query": normalized_query,
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
        # Fallback to name search
        candidates = _restaurant_candidates(db, payload.restaurant_name)
        if candidates:
            best_candidate = candidates[0]
            # Try to disambiguate if multiple restaurants have similar names by checking known valid IDs
            if payload.known_restaurant_ids:
                for c in candidates:
                    if c["id"] in payload.known_restaurant_ids:
                        best_candidate = c
                        break
                        
            restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == best_candidate["id"]).first()
            if restaurant:
                # Update payload to use the correct ID so downstream code works seamlessly if needed
                payload.restaurant_id = restaurant.id

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
                    for item in items[:8]
                ],
            }
        )

    item_query = payload.query or restaurant.name
    suggestions = _item_candidates(db, item_query, restaurant.id) if payload.query else []
    
    if not categories_payload and not suggestions:
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
        "suggested_items": suggestions,
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
    item, restaurant, category = _resolve_item_with_fallback(
        db, payload.item_id, payload.item_name, payload.restaurant_id
    )
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
    item, restaurant, category = _resolve_item_with_fallback(
        db, payload.item_id, payload.item_name, payload.restaurant_id
    )
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

def _execute_vapi_tool(
    name: str,
    arguments: dict,
    session_id: str,
    db: Session,
) -> dict:
    """Dispatch a Vapi tool call to the matching backend handler."""
    if name == "list_restaurants":
        session = _get_or_create_call_session(db, session_id, "en-IN")
        restaurants = crud.list_restaurants(db)
        query = str(arguments.get("query") or "")
        limit = int(arguments.get("limit") or 8)
        normalized_query = _restaurant_request_phrase(query) or _normalize_spoken_text(query)
        filtered = [
            r for r in restaurants
            if not normalized_query
            or normalized_query in r.name.lower()
            or normalized_query in (r.city or "").lower()
        ]
        if normalized_query and not filtered:
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
        query = str(arguments.get("query") or "")
        matches = _restaurant_candidates(db, query)
        return {
            "query": query,
            "restaurants": [
                {"id": m["id"], "name": m["name"], "score": m.get("score")}
                for m in matches[:5]
            ],
        }

    if name == "get_restaurant_menu":
        _get_or_create_call_session(db, session_id, "en-IN")
        restaurant_id = int(arguments.get("restaurant_id", 0))
        query = str(arguments.get("query") or "")
        restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
        if not restaurant:
            return {"error": "Restaurant not found"}
        categories_payload: list[dict] = []
        for cat in crud.list_categories(db, restaurant.id):
            items = crud.list_items(db, cat.id)
            categories_payload.append({
                "id": cat.id,
                "name": cat.name,
                "items": [{"id": i.id, "name": i.name, "price_cents": i.price_cents} for i in items[:5]],
            })
        suggestions = _item_candidates(db, query, restaurant.id) if query else []
        return {
            "restaurant": {"id": restaurant.id, "name": restaurant.name},
            "categories": [c for c in categories_payload[:5]],
            "suggested_items": suggestions[:5],
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
            result = _execute_vapi_tool(tc_name, tc_args, session_id, db)
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
