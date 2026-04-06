from __future__ import annotations

import json as _json
import os
from typing import Optional
import urllib.request
import urllib.error
import urllib.parse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, status
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import chat, crud, group_consensus, intent_extractor, models, optimizer, payments, schemas
from .auth import create_access_token, get_current_user, get_current_user_optional, verify_password
from .config import settings
from .db import get_db, engine
from .voice import router as voice_router
from .voice_ws import router as voice_ws_router
from .ai_dashboard import router as ai_dashboard_router
from .call_order import router as call_order_router
from .ai_call_realtime import router as ai_call_realtime_router

try:
    models.Base.metadata.create_all(bind=engine)
except Exception as _db_err:
    print(f"[startup] DB create_all skipped: {_db_err}")


def _ensure_chat_sessions_columns():
    """Add missing columns to chat_sessions if the table was created before they existed (e.g. status, updated_at)."""
    from sqlalchemy import text
    is_sqlite = "sqlite" in settings.database_url
    if is_sqlite:
        statements = [
            "ALTER TABLE chat_sessions ADD COLUMN status TEXT DEFAULT 'active'",
            "ALTER TABLE chat_sessions ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP",
        ]
    else:
        statements = [
            "ALTER TABLE chat_sessions ADD COLUMN status VARCHAR(40) DEFAULT 'active' NOT NULL",
            "ALTER TABLE chat_sessions ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL",
        ]
    with engine.connect() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                msg = str(e).lower()
                if "already exists" in msg or "duplicate column" in msg or "duplicate_column_name" in msg:
                    conn.rollback()
                    continue
                conn.rollback()
                raise


def _ensure_menu_items_columns():
    """Add missing columns to menu_items (e.g. is_available, cuisine, tags) so list_items and recommendations work."""
    from sqlalchemy import text
    is_sqlite = "sqlite" in settings.database_url
    if is_sqlite:
        statements = [
            "ALTER TABLE menu_items ADD COLUMN is_available INTEGER DEFAULT 1",
            "ALTER TABLE menu_items ADD COLUMN portion_people INTEGER",
            "ALTER TABLE menu_items ADD COLUMN cuisine TEXT",
            "ALTER TABLE menu_items ADD COLUMN protein_type TEXT",
            "ALTER TABLE menu_items ADD COLUMN tags TEXT",
            "ALTER TABLE menu_items ADD COLUMN calories INTEGER",
            "ALTER TABLE menu_items ADD COLUMN prep_time_mins INTEGER",
        ]
    else:
        statements = [
            "ALTER TABLE menu_items ADD COLUMN is_available BOOLEAN DEFAULT TRUE NOT NULL",
            "ALTER TABLE menu_items ADD COLUMN portion_people INTEGER",
            "ALTER TABLE menu_items ADD COLUMN cuisine VARCHAR(60)",
            "ALTER TABLE menu_items ADD COLUMN protein_type VARCHAR(40)",
            "ALTER TABLE menu_items ADD COLUMN tags TEXT",
            "ALTER TABLE menu_items ADD COLUMN calories INTEGER",
            "ALTER TABLE menu_items ADD COLUMN prep_time_mins INTEGER",
        ]
    with engine.connect() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                msg = str(e).lower()
                if "already exists" in msg or "duplicate column" in msg or "duplicate_column_name" in msg:
                    conn.rollback()
                    continue
                conn.rollback()
                raise


def _ensure_taste_profiles_columns():
    """Add updated_at to taste_profiles if missing."""
    from sqlalchemy import text
    is_sqlite = "sqlite" in settings.database_url
    sql = "ALTER TABLE taste_profiles ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP" if is_sqlite else "ALTER TABLE taste_profiles ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL"
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                conn.rollback()
                return
            conn.rollback()
            raise


def _ensure_order_items_menu_item_nullable():
    """Allow order_items.menu_item_id to be NULL so menu can be replaced without breaking order history (FK)."""
    from sqlalchemy import text
    if "sqlite" in settings.database_url:
        return  # SQLite: NOT NULL can't be dropped without table recreate; new DBs get nullable from model
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE order_items ALTER COLUMN menu_item_id DROP NOT NULL"))
            conn.commit()
        except Exception as e:
            msg = str(e).lower()
            if "does not exist" in msg or "already" in msg or "cannot drop" in msg:
                conn.rollback()
                return
            conn.rollback()
            raise


app = FastAPI(title="RestarentAI")
app.include_router(voice_router)
app.include_router(voice_ws_router)
app.include_router(ai_dashboard_router)
app.include_router(call_order_router)
app.include_router(ai_call_realtime_router)

@app.on_event("startup")
def startup_event():
    try:
        _ensure_chat_sessions_columns()
    except Exception as e:
        print(f"[startup] chat_sessions columns check skipped: {e}")
    try:
        _ensure_menu_items_columns()
    except Exception as e:
        print(f"[startup] menu_items columns check skipped: {e}")
    try:
        _ensure_taste_profiles_columns()
    except Exception as e:
        print(f"[startup] taste_profiles columns check skipped: {e}")
    try:
        _ensure_order_items_menu_item_nullable()
    except Exception as e:
        print(f"[startup] order_items menu_item_id nullable check skipped: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/sarvam")
async def health_sarvam():
    """Check if Sarvam AI chat API is configured and callable (used for menu item matching)."""
    from . import sarvam_service
    ok, err = sarvam_service.check_chat_available()
    if ok:
        return {"status": "ok", "sarvam": "available"}
    return {"status": "degraded", "sarvam": "unavailable", "error": err}


# Global exception handler for better error diagnostics on Vercel
from fastapi.responses import JSONResponse
import traceback

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    tb = traceback.format_exc()
    print(f"[ERROR] {exc}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


# --- AI Budget Optimizer ---
@app.post("/ai/meal-optimizer", response_model=schemas.MealOptimizerResponse)
def meal_optimizer(
    payload: schemas.MealOptimizerRequest,
    db: Session = Depends(get_db),
):
    """Find the best meal combos to feed N people under a budget."""
    results = optimizer.optimize_meal(
        db,
        people=payload.people,
        budget_cents=payload.budget_cents,
        cuisine=payload.cuisine,
        restaurant_id=payload.restaurant_id,
    )
    return schemas.MealOptimizerResponse(
        combos=results,
        people_requested=payload.people,
        budget_cents=payload.budget_cents,
    )


# --- Multi-restaurant cart helper ---
def _build_cart_summary(db: Session, user_id: int) -> dict:
    """Build grouped cart data across all pending orders for a user. Totals are always computed from item line totals (never trust order.total_cents for display)."""
    try:
        pending_orders = crud.get_user_pending_orders(db, user_id)
    except Exception:
        return {"restaurants": [], "grand_total_cents": 0}
    groups = []
    grand_total = 0
    for order in pending_orders:
        try:
            restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == order.restaurant_id).first()
            items = []
            for oi in order.items:
                mi = db.query(models.MenuItem).filter(models.MenuItem.id == oi.menu_item_id).first()
                price_cents = getattr(oi, "price_cents", 0) or 0
                quantity = getattr(oi, "quantity", 0) or 0
                # Fix likely double-converted price (e.g. 129900 instead of 1299): if value is 100x a reasonable price, use /100
                if price_cents >= 10000 and price_cents % 100 == 0:
                    candidate = price_cents // 100
                    if 1 <= candidate <= 10000:  # $0.01 to $100 per item
                        price_cents = candidate
                line_total = price_cents * quantity
                items.append({
                    "order_item_id": oi.id,
                    "name": mi.name if mi else f"Item #{oi.menu_item_id}",
                    "quantity": quantity,
                    "price_cents": price_cents,
                    "line_total_cents": line_total,
                })
            # Always compute subtotal from items so cart total is correct even if order.total_cents is stale/wrong
            subtotal = sum(i["line_total_cents"] for i in items)
            if items:
                groups.append({
                    "restaurant_id": order.restaurant_id,
                    "restaurant_name": restaurant.name if restaurant else "Unknown",
                    "order_id": order.id,
                    "items": items,
                    "subtotal_cents": subtotal,
                })
                grand_total += subtotal
        except Exception:
            continue
    return {"restaurants": groups, "grand_total_cents": grand_total}


@app.get("/cart")
def get_cart(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all pending orders grouped by restaurant for the current user."""
    return _build_cart_summary(db, current_user.id)


@app.delete("/cart/item/{order_item_id}")
def remove_cart_item(
    order_item_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Remove a single item from the cart."""
    oi = db.query(models.OrderItem).filter(models.OrderItem.id == order_item_id).first()
    if not oi:
        raise HTTPException(status_code=404, detail="Item not found")
    order = db.query(models.Order).filter(models.Order.id == oi.order_id).first()
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your order")
    db.delete(oi)
    db.commit()
    crud.recompute_order_total(db, order)
    # If order has no items left, clean up the order
    remaining = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).count()
    if remaining == 0:
        _detach_and_delete_order(db, order)
    return _build_cart_summary(db, current_user.id)


def _detach_and_delete_order(db: Session, order):
    """Nullify FK references in chat_sessions & payments, then delete the order."""
    db.query(models.ChatSession).filter(models.ChatSession.order_id == order.id).update({"order_id": None})
    db.query(models.Payment).filter(models.Payment.order_id == order.id).update({"order_id": None})
    db.delete(order)
    db.commit()


@app.delete("/cart/clear")
def clear_cart(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Clear all pending orders for the current user."""
    pending_orders = crud.get_user_pending_orders(db, current_user.id)
    for order in pending_orders:
        for oi in order.items:
            db.delete(oi)
        _detach_and_delete_order(db, order)
    return _build_cart_summary(db, current_user.id)


class ComboItem(BaseModel):
    item_id: int
    quantity: int


class AddComboRequest(BaseModel):
    restaurant_id: int
    items: list[ComboItem]


@app.post("/cart/add-combo")
def add_combo_to_cart(
    payload: AddComboRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Add multiple items to cart in one shot (used by Budget Optimizer)."""
    order = crud.get_user_order_for_restaurant(db, current_user.id, payload.restaurant_id)
    if not order:
        order = crud.create_order(db, current_user.id, payload.restaurant_id)

    for ci in payload.items:
        menu_item = db.query(models.MenuItem).filter(models.MenuItem.id == ci.item_id).first()
        if menu_item:
            crud.add_order_item(db, order, menu_item, ci.quantity)

    crud.recompute_order_total(db, order)
    return _build_cart_summary(db, current_user.id)


@app.post("/auth/register", response_model=schemas.Token)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if crud.get_user_by_email(db, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = crud.create_user(db, payload.email, payload.password)
    token = create_access_token(user.email)
    return {"access_token": token, "role": user.role}


@app.post("/auth/login", response_model=schemas.Token)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.email)
    return {"access_token": token, "role": user.role}


import math, urllib.request, urllib.parse, json as _json

def _haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.get("/nearby")
def nearby_restaurants(lat: float, lng: float, radius_miles: float = 10.0):
    """Discover real restaurants nearby using OpenStreetMap Overpass API."""
    radius_m = int(radius_miles * 1609.34)  # miles to meters
    query = f"[out:json];node[amenity=restaurant](around:{radius_m},{lat},{lng});out body 20;"
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)

    try:
        req = urllib.request.urlopen(url, timeout=10)
        data = _json.loads(req.read())
    except Exception:
        return []

    results = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        r_lat = el.get("lat", 0)
        r_lng = el.get("lon", 0)
        dist = round(_haversine_mi(lat, lng, r_lat, r_lng), 1)
        results.append({
            "name": name,
            "cuisine": tags.get("cuisine", ""),
            "address": tags.get("addr:street", tags.get("addr:full", "")),
            "phone": tags.get("phone", ""),
            "latitude": r_lat,
            "longitude": r_lng,
            "distance_miles": dist,
            "source": "openstreetmap",
        })

    results.sort(key=lambda x: x["distance_miles"])
    return results


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in miles between two coordinates."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.get("/restaurants", response_model=list[schemas.RestaurantOut])
def restaurants(
    query: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_miles: float = 25.0,
    db: Session = Depends(get_db),
):
    try:
        all_restaurants = crud.list_restaurants(db, query)
    except Exception as e:
        print(f"[ERROR] /restaurants list_restaurants failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {str(e)}. Check DATABASE_URL and that the DB is running.",
        ) from e

    if lat is not None and lng is not None:
        results = []
        for r in all_restaurants:
            has_coords = (r.latitude is not None and r.longitude is not None
                         and not (r.latitude == 0.0 and r.longitude == 0.0))
            if has_coords:
                dist = _haversine(lat, lng, r.latitude, r.longitude)
                if dist <= radius_miles:
                    out = schemas.RestaurantOut.model_validate(r)
                    out.distance_miles = round(dist, 1)
                    results.append(out)
            else:
                # Restaurants without valid coords always show
                out = schemas.RestaurantOut.model_validate(r)
                out.distance_miles = None
                results.append(out)
        results.sort(key=lambda x: x.distance_miles if x.distance_miles is not None else 9999)
        return results

    # No geo: return all restaurants as RestaurantOut (consistent serialization)
    return [schemas.RestaurantOut.model_validate(r) for r in all_restaurants]


# ── Cross-Restaurant Price Comparison ─────────────────────────────────

_STOP_WORDS = {
    "i", "a", "an", "the", "is", "am", "are", "was", "were", "be", "been",
    "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "may", "might", "shall", "to", "of", "in", "on",
    "at", "for", "with", "from", "by", "it", "its", "my", "me", "we",
    "us", "you", "your", "he", "she", "they", "them", "this", "that",
    "want", "need", "get", "find", "buy", "give", "show", "where",
    "what", "which", "how", "much", "many", "some", "any", "all",
    "please", "just", "like", "also", "very", "really", "about",
    "nearby", "near", "here", "around", "cheapest", "cheap", "compare",
    "price", "best", "value", "lowest",
}


def _edit_distance(a: str, b: str) -> int:
    """Simple Levenshtein distance for fuzzy matching."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[len(b)]


def _fuzzy_match(keyword: str, text: str) -> bool:
    """Check if keyword appears in text — exact substring OR fuzzy (edit distance ≤ 2)."""
    if keyword in text:
        return True
    # Check each word in text for fuzzy match
    for word in text.split():
        word_clean = word.strip("(),.-!?")
        if len(keyword) >= 3 and len(word_clean) >= 3:
            threshold = 1 if len(keyword) <= 5 else 2
            if _edit_distance(keyword, word_clean) <= threshold:
                return True
    return False


@app.get("/search/menu-items", response_model=schemas.PriceComparisonResponse)
def search_menu_items(q: str = "", db: Session = Depends(get_db)):
    """Search for a menu item across ALL restaurants — sorted cheapest first."""
    query = q.strip()
    if not query or len(query) < 2:
        raise HTTPException(400, "Search query must be at least 2 characters")

    # Extract meaningful keywords (remove stop words)
    raw_keywords = query.lower().split()
    keywords = [kw for kw in raw_keywords if kw not in _STOP_WORDS and len(kw) >= 2]

    # If all words were stop words, use the longest raw keyword as fallback
    if not keywords:
        keywords = sorted(raw_keywords, key=len, reverse=True)[:1]
    if not keywords:
        raise HTTPException(400, "Search query must contain meaningful words")

    # Join MenuItem → MenuCategory → Restaurant
    rows = (
        db.query(models.MenuItem, models.Restaurant)
        .join(models.MenuCategory, models.MenuItem.category_id == models.MenuCategory.id)
        .join(models.Restaurant, models.MenuCategory.restaurant_id == models.Restaurant.id)
        .filter(models.MenuItem.is_available.is_(True))
        .filter(models.Restaurant.is_active.is_(True))
        .filter(models.MenuItem.price_cents > 0)  # Exclude $0 items
        .all()
    )

    # Score each item — require ALL keywords to match (exact or fuzzy)
    scored = []
    for item, restaurant in rows:
        item_name_lower = item.name.lower()
        matched = sum(1 for kw in keywords if _fuzzy_match(kw, item_name_lower))
        if matched == len(keywords):  # ALL keywords must match
            # Bonus: exact substring match scores higher
            exact_bonus = sum(1 for kw in keywords if kw in item_name_lower)
            scored.append((matched + exact_bonus, item, restaurant))

    # Sort by match score DESC, then price ASC
    scored.sort(key=lambda x: (-x[0], x[1].price_cents))

    results = []
    for _score, item, restaurant in scored:
        results.append(schemas.PriceComparisonItem(
            item_id=item.id,
            item_name=item.name,
            price_cents=item.price_cents,
            restaurant_name=restaurant.name,
            restaurant_id=restaurant.id,
            city=restaurant.city,
            rating=restaurant.rating,
            description=item.description,
        ))

    best_value = results[0] if results else None

    return schemas.PriceComparisonResponse(
        query=query,
        results=results,
        best_value=best_value,
    )


@app.get("/search/popular", response_model=schemas.PriceComparisonResponse)
def popular_items(db: Session = Depends(get_db)):
    """Return a diverse selection of popular food items across all restaurants.

    Used for discovery queries like 'i dont know what to eat'.
    Filters out drinks/sides (items under $5) and returns 1 item per restaurant,
    sorted by price ascending, max 10 items.
    """
    # All available food items (price >= $5 to skip drinks/sides/extras)
    rows = (
        db.query(models.MenuItem, models.Restaurant)
        .join(models.MenuCategory, models.MenuItem.category_id == models.MenuCategory.id)
        .join(models.Restaurant, models.MenuCategory.restaurant_id == models.Restaurant.id)
        .filter(models.MenuItem.is_available.is_(True))
        .filter(models.Restaurant.is_active.is_(True))
        .filter(models.MenuItem.price_cents >= 500)   # $5+ = real food items
        .filter(models.MenuItem.price_cents <= 3000)   # Under $30 = reasonable
        .order_by(models.MenuItem.price_cents.asc())
        .all()
    )

    # Pick 1 item per restaurant for maximum diversity
    seen_restaurants: set[int] = set()
    results = []
    for item, restaurant in rows:
        if restaurant.id in seen_restaurants:
            continue
        seen_restaurants.add(restaurant.id)
        results.append(schemas.PriceComparisonItem(
            item_id=item.id,
            item_name=item.name,
            price_cents=item.price_cents,
            restaurant_name=restaurant.name,
            restaurant_id=restaurant.id,
            city=restaurant.city,
            rating=restaurant.rating,
            description=item.description,
        ))
        if len(results) >= 10:
            break

    best_value = results[0] if results else None
    return schemas.PriceComparisonResponse(
        query="Popular picks for you",
        results=results,
        best_value=best_value,
    )


class IntentSearchRequest(BaseModel):
    text: str


@app.post("/search/intent", response_model=schemas.PriceComparisonResponse)
def search_by_intent(req: IntentSearchRequest, db: Session = Depends(get_db)):
    """Smart intent-based search: extract intent from natural language, then query DB."""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Text is required")

    # Extract structured intent from user message (use LLM + local hybrid extractor)
    intent = intent_extractor.extract_intent(text, use_llm=True)

    # Build query
    query = (
        db.query(models.MenuItem, models.Restaurant)
        .join(models.MenuCategory, models.MenuItem.category_id == models.MenuCategory.id)
        .join(models.Restaurant, models.MenuCategory.restaurant_id == models.Restaurant.id)
        .filter(models.MenuItem.is_available.is_(True))
        .filter(models.Restaurant.is_active.is_(True))
        .filter(models.MenuItem.price_cents > 0)
    )

    # --- Recommendation mode: return diverse popular items ---
    if intent.recommendation_mode and not intent.dish_name:
        query = query.filter(models.MenuItem.price_cents >= 500)
        query = query.filter(models.MenuItem.price_cents <= 3000)
        rows = query.order_by(models.MenuItem.price_cents.asc()).all()

        # Apply cuisine / diet / protein filters if specified
        rows = _filter_rows(rows, intent)

        # 1 per restaurant for diversity
        seen: set[int] = set()
        results = []
        for item, restaurant in rows:
            if restaurant.id in seen:
                continue
            seen.add(restaurant.id)
            results.append(_to_comparison_item(item, restaurant))
            if len(results) >= 10:
                break

        display_query = _build_display_query(intent)
        best_value = results[0] if results else None
        return schemas.PriceComparisonResponse(
            query=display_query or "\U0001f525 Popular picks for you",
            results=results,
            best_value=best_value,
        )

    # --- Dish search mode ---
    rows = query.order_by(models.MenuItem.price_cents.asc()).all()

    # Apply cuisine / diet / protein filters
    rows = _filter_rows(rows, intent)

    # Apply price filter
    if intent.price_max:
        max_cents = int(intent.price_max * 100)
        rows = [(i, r) for i, r in rows if i.price_cents <= max_cents]

    # Fuzzy dish name matching
    if intent.dish_name:
        keywords = intent.dish_name.lower().split()
        scored = []
        for item, restaurant in rows:
            name_lower = item.name.lower()
            matched = sum(1 for kw in keywords if _fuzzy_match(kw, name_lower))
            if matched >= max(1, len(keywords) // 2):  # At least half keywords match
                exact_bonus = sum(1 for kw in keywords if kw in name_lower)
                scored.append((matched + exact_bonus, item, restaurant))
        scored.sort(key=lambda x: (-x[0], x[1].price_cents))
        rows = [(item, rest) for _, item, rest in scored]
    else:
        # No dish name but has other filters (cuisine, diet, etc.)
        # Return diverse results
        seen_r: set[int] = set()
        diverse = []
        for item, restaurant in rows:
            if restaurant.id in seen_r:
                continue
            seen_r.add(restaurant.id)
            diverse.append((item, restaurant))
            if len(diverse) >= 10:
                break
        rows = diverse

    results = [_to_comparison_item(item, rest) for item, rest in rows[:15]]
    display_query = _build_display_query(intent)

    # --- Fallback: if 0 results, return popular items instead of empty ---
    if not results:
        fallback_q = (
            db.query(models.MenuItem, models.Restaurant)
            .join(models.MenuCategory, models.MenuItem.category_id == models.MenuCategory.id)
            .join(models.Restaurant, models.MenuCategory.restaurant_id == models.Restaurant.id)
            .filter(models.MenuItem.is_available.is_(True))
            .filter(models.Restaurant.is_active.is_(True))
            .filter(models.MenuItem.price_cents > 0)
            .filter(models.MenuItem.price_cents >= 500)
            .filter(models.MenuItem.price_cents <= 3000)
            .order_by(models.MenuItem.price_cents.asc())
            .all()
        )
        seen_fb: set[int] = set()
        for item, restaurant in fallback_q:
            if restaurant.id in seen_fb:
                continue
            seen_fb.add(restaurant.id)
            results.append(_to_comparison_item(item, restaurant))
            if len(results) >= 10:
                break
        fallback_label = f"🔍 No exact match for \"{intent.dish_name or text}\" — here are popular picks"
        display_query = fallback_label

    best_value = results[0] if results else None

    return schemas.PriceComparisonResponse(
        query=display_query or text,
        results=results,
        best_value=best_value,
    )


def _filter_rows(rows, intent):
    """Apply cuisine / diet / protein filters to rows."""
    filtered = rows
    if intent.cuisine:
        cuisine_lower = intent.cuisine.lower()
        filtered = [
            (i, r) for i, r in filtered
            if (i.cuisine and cuisine_lower in i.cuisine.lower())
            or (r.name and cuisine_lower in r.name.lower())
            or (i.description and cuisine_lower in i.description.lower())
        ]
        # If no results with strict filter, return unfiltered
        if not filtered:
            filtered = rows

    if intent.protein_type:
        protein_lower = intent.protein_type.lower()
        strict = [
            (i, r) for i, r in filtered
            if (i.protein_type and protein_lower in i.protein_type.lower())
            or protein_lower in i.name.lower()
            or (i.description and protein_lower in i.description.lower())
        ]
        if strict:
            filtered = strict

    if intent.diet_type:
        diet_lower = intent.diet_type.lower().replace("-", "")
        # For vegetarian/vegan, filter by name keywords
        veg_keywords = ["veg", "paneer", "tofu", "mushroom", "plant"]
        if "veg" in diet_lower:
            strict = [
                (i, r) for i, r in filtered
                if any(kw in i.name.lower() for kw in veg_keywords)
                or (i.description and any(kw in i.description.lower() for kw in veg_keywords))
            ]
            if strict:
                filtered = strict

    return filtered


def _to_comparison_item(item, restaurant) -> schemas.PriceComparisonItem:
    return schemas.PriceComparisonItem(
        item_id=item.id,
        item_name=item.name,
        price_cents=item.price_cents,
        restaurant_name=restaurant.name,
        restaurant_id=restaurant.id,
        city=restaurant.city,
        rating=restaurant.rating,
        description=item.description,
    )


def _build_display_query(intent) -> str:
    """Build a human-readable display query from the intent."""
    parts = []
    if intent.dish_name:
        parts.append(intent.dish_name)
    if intent.cuisine:
        parts.append(intent.cuisine)
    if intent.protein_type and intent.protein_type not in (intent.dish_name or ""):
        parts.append(intent.protein_type)
    if intent.diet_type:
        parts.append(intent.diet_type)
    if intent.price_max:
        parts.append(f"under ${intent.price_max:.0f}")
    if intent.people_count:
        parts.append(f"for {intent.people_count} people")
    if intent.budget_total:
        parts.append(f"budget ${intent.budget_total:.0f}")
    if intent.recommendation_mode and not parts:
        return "\U0001f525 Popular picks for you"
    return " · ".join(parts) if parts else ""


# ─── Meal Plan Endpoints ──────────────────────────────────────────────────

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class MealPlanRequest(BaseModel):
    text: str


@app.post("/mealplan/generate", response_model=schemas.MealPlanResponse)
def generate_meal_plan(req: MealPlanRequest, db: Session = Depends(get_db)):
    """Generate a diverse weekly meal plan within budget using the Diversity Engine."""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Text is required")

    intent = intent_extractor.extract_intent(text, use_llm=False)

    plan_days = intent.plan_days or 5
    people = intent.people_count or 1
    budget_cents = int((intent.budget_total or intent.price_max or 100) * 100)
    per_meal_cents = budget_cents // plan_days

    # Query all available items (real meals only, min $5)
    EXCLUDE_KEYWORDS = {"water", "soda", "coke", "pepsi", "sprite", "fanta", "juice",
                         "milkshake", "shake", "smoothie", "lassi", "tea", "coffee", "lemonade", "chaas", "buttermilk",
                         "naan", "pav", "rice", "roti", "bread", "raita", "sauce",
                         "chutney", "pickle", "papad", "pappadam", "sambar",
                         "extra", "add-on", "utensil", "cutlery", "napkin", "ice cream", "dessert"}
    min_price = 500  # $5.00 minimum for actual meals
    rows = (
        db.query(models.MenuItem, models.Restaurant)
        .join(models.MenuCategory, models.MenuItem.category_id == models.MenuCategory.id)
        .join(models.Restaurant, models.MenuCategory.restaurant_id == models.Restaurant.id)
        .filter(models.MenuItem.is_available.is_(True))
        .filter(models.Restaurant.is_active.is_(True))
        .filter(models.MenuItem.price_cents >= min_price)
        .filter(models.MenuItem.price_cents <= per_meal_cents)
        .all()
    )
    # Filter out beverages/sides by name
    rows = [(i, r) for i, r in rows if not any(kw in i.name.lower() for kw in EXCLUDE_KEYWORDS)]
    # Shuffle for variety instead of cheapest-first
    import random
    random.shuffle(rows)

    # Apply cuisine / diet / protein filters from intent
    rows = _filter_rows(rows, intent)

    if not rows:
        # Fallback: relax price filter
        rows = (
            db.query(models.MenuItem, models.Restaurant)
            .join(models.MenuCategory, models.MenuItem.category_id == models.MenuCategory.id)
            .join(models.Restaurant, models.MenuCategory.restaurant_id == models.Restaurant.id)
            .filter(models.MenuItem.is_available.is_(True))
            .filter(models.Restaurant.is_active.is_(True))
            .filter(models.MenuItem.price_cents > 0)
            .filter(models.MenuItem.price_cents <= 3000)
            .order_by(models.MenuItem.price_cents.asc())
            .all()
        )

    # ── Diversity Engine ─────────────────────────────────────
    # Rules: max 2 same cuisine, max 2 same restaurant, no repeat dishes
    MAX_SAME_CUISINE = 2
    MAX_SAME_RESTAURANT = 2

    cuisine_count: dict[str, int] = {}
    restaurant_count: dict[int, int] = {}
    used_items: set[int] = set()
    plan_days_list: list[schemas.MealPlanDay] = []
    total_cents = 0

    for day_idx in range(plan_days):
        best_pick = None
        for item, restaurant in rows:
            if item.id in used_items:
                continue

            item_cuisine = (item.cuisine or restaurant.name or "other").lower()
            r_id = restaurant.id

            # Check diversity constraints
            if cuisine_count.get(item_cuisine, 0) >= MAX_SAME_CUISINE:
                continue
            if restaurant_count.get(r_id, 0) >= MAX_SAME_RESTAURANT:
                continue

            # Check budget
            if total_cents + item.price_cents > budget_cents:
                continue

            best_pick = (item, restaurant, item_cuisine)
            break

        if not best_pick:
            # Relax constraints: allow any item that fits budget
            for item, restaurant in rows:
                if item.id in used_items:
                    continue
                if total_cents + item.price_cents <= budget_cents:
                    item_cuisine = (item.cuisine or restaurant.name or "other").lower()
                    best_pick = (item, restaurant, item_cuisine)
                    break

        if best_pick:
            item, restaurant, item_cuisine = best_pick
            used_items.add(item.id)
            cuisine_count[item_cuisine] = cuisine_count.get(item_cuisine, 0) + 1
            restaurant_count[restaurant.id] = restaurant_count.get(restaurant.id, 0) + 1
            total_cents += item.price_cents

            plan_days_list.append(schemas.MealPlanDay(
                day=DAY_NAMES[day_idx % 7],
                item_id=item.id,
                item_name=item.name,
                restaurant_name=restaurant.name,
                restaurant_id=restaurant.id,
                price_cents=item.price_cents,
                cuisine=item.cuisine or None,
                description=item.description or None,
            ))

    savings = budget_cents - total_cents

    # ── AI Summary ────────────────────────────────────────────
    cuisines_used = list(set(d.cuisine or d.restaurant_name for d in plan_days_list))
    restaurants_used = list(set(d.restaurant_name for d in plan_days_list))
    summary = (
        f"🍽️ Your {len(plan_days_list)}-day meal plan is ready! "
        f"Total cost: ${total_cents / 100:.2f} "
        f"(${savings / 100:.2f} under your ${budget_cents / 100:.0f} budget). "
        f"Includes dishes from {', '.join(restaurants_used[:3])}{'...' if len(restaurants_used) > 3 else ''}"
        f" across {len(cuisines_used)} {'cuisine' if len(cuisines_used) == 1 else 'cuisines'}."
    )

    return schemas.MealPlanResponse(
        days=plan_days_list,
        total_cents=total_cents,
        budget_cents=budget_cents,
        savings_cents=savings,
        people_count=people,
        ai_summary=summary,
    )


class MealSwapRequest(BaseModel):
    text: str
    day_index: int
    current_item_id: int
    budget_remaining_cents: int


@app.post("/mealplan/swap", response_model=schemas.MealPlanDay)
def swap_meal(req: MealSwapRequest, db: Session = Depends(get_db)):
    """Swap a single meal in the plan with a different diverse option."""
    rows = (
        db.query(models.MenuItem, models.Restaurant)
        .join(models.MenuCategory, models.MenuItem.category_id == models.MenuCategory.id)
        .join(models.Restaurant, models.MenuCategory.restaurant_id == models.Restaurant.id)
        .filter(models.MenuItem.is_available.is_(True))
        .filter(models.Restaurant.is_active.is_(True))
        .filter(models.MenuItem.price_cents > 0)
        .filter(models.MenuItem.price_cents <= req.budget_remaining_cents)
        .filter(models.MenuItem.id != req.current_item_id)
        .order_by(models.MenuItem.price_cents.asc())
        .all()
    )

    if not rows:
        raise HTTPException(404, "No alternative meals found within budget")

    # Pick a random different item for variety
    import random
    pick_pool = rows[:min(20, len(rows))]
    item, restaurant = random.choice(pick_pool)

    return schemas.MealPlanDay(
        day=DAY_NAMES[req.day_index % 7],
        item_id=item.id,
        item_name=item.name,
        restaurant_name=restaurant.name,
        restaurant_id=restaurant.id,
        price_cents=item.price_cents,
        cuisine=item.cuisine or None,
        description=item.description or None,
    )


@app.get("/restaurants/{restaurant_id}/categories", response_model=list[schemas.MenuCategoryOut])
def restaurant_categories(restaurant_id: int, db: Session = Depends(get_db)):
    return crud.list_categories(db, restaurant_id)


@app.get("/categories/{category_id}/items", response_model=list[schemas.MenuItemOut])
def category_items(category_id: int, db: Session = Depends(get_db)):
    return crud.list_items(db, category_id)


@app.post("/chat/session", response_model=schemas.ChatSessionOut)
def start_session(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = crud.create_chat_session(db, current_user.id)
    return session


@app.post("/chat/message", response_model=schemas.ChatMessageOut)
def send_message(
    payload: schemas.ChatMessageIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if payload.session_id is None:
        session = crud.create_chat_session(db, current_user.id)
    else:
        try:
            session = (
                db.query(models.ChatSession)
                .filter(models.ChatSession.id == payload.session_id)
                .first()
            )
        except Exception as e:
            if "column" in str(e).lower() or "undefined" in str(e).lower():
                try:
                    _ensure_chat_sessions_columns()
                except Exception:
                    pass
                session = (
                    db.query(models.ChatSession)
                    .filter(models.ChatSession.id == payload.session_id)
                    .first()
                )
            else:
                raise
        if not session or session.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if "restaurant_id" in payload.model_fields_set:
        requested_restaurant_id = payload.restaurant_id
        if requested_restaurant_id is None:
            if session.restaurant_id is not None or session.category_id is not None or session.order_id is not None:
                chat._set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)
        elif session.restaurant_id != requested_restaurant_id:
            existing_order = crud.get_user_order_for_restaurant(db, current_user.id, requested_restaurant_id)
            chat._set_session_state(
                db,
                session,
                restaurant_id=requested_restaurant_id,
                category_id=None,
                order_id=existing_order.id if existing_order else None,
            )

    crud.add_chat_message(db, session.id, "user", payload.text)
    result = chat.process_message(db, session, payload.text, user_lat=payload.lat, user_lng=payload.lng)
    crud.add_chat_message(db, session.id, "bot", result["reply"])

    return schemas.ChatMessageOut(
        session_id=session.id,
        reply=result["reply"],
        restaurant_id=result.get("restaurant_id"),
        category_id=result.get("category_id"),
        order_id=result.get("order_id"),
        categories=result.get("categories"),
        items=result.get("items"),
        cart_summary=result.get("cart_summary"),
        voice_prompt=result.get("voice_prompt"),
        open_group_tab=result.get("open_group_tab"),
    )


# =============================================================
# Phase 2: Restaurant Owner Onboarding Portal
# =============================================================

import re as _re

def _slugify(name: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# --- Owner registration ---
@app.post("/auth/register-owner", response_model=schemas.Token)
def register_owner(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    """Register as a restaurant owner, or log in if already registered."""
    from passlib.hash import bcrypt
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        # Verify password — treat as login
        if not bcrypt.verify(payload.password, existing.password_hash):
            raise HTTPException(status_code=401, detail="Invalid password")
        # Upgrade role to owner if still a customer
        if existing.role == "customer":
            existing.role = "owner"
            db.commit()
        token = create_access_token(existing.email)
        return {"access_token": token, "role": existing.role}
    # New user — register as owner
    user = models.User(
        email=payload.email,
        password_hash=bcrypt.hash(payload.password),
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.email)
    return {"access_token": token, "role": user.role}


# --- My restaurants ---
@app.get("/owner/restaurants", response_model=list[schemas.RestaurantOut])
def owner_restaurants(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")
    return db.query(models.Restaurant).filter(models.Restaurant.owner_id == current_user.id).all()


@app.post("/owner/claim-all")
def claim_all_restaurants(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Admin/owner: assign ALL restaurants to the current user."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    restaurants = db.query(models.Restaurant).all()
    count = 0
    for r in restaurants:
        r.owner_id = current_user.id
        count += 1
    db.commit()
    return {"claimed": count, "user_id": current_user.id}

@app.post("/owner/restaurants", response_model=schemas.RestaurantOut)
def create_restaurant(payload: schemas.RestaurantCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")
    slug = _slugify(payload.name)
    # Ensure unique slug
    base_slug = slug
    counter = 1
    while db.query(models.Restaurant).filter(models.Restaurant.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    # Auto-geocode if lat/lng not provided but address exists
    r_lat = payload.latitude
    r_lng = payload.longitude
    if (r_lat is None or r_lat == 0) and payload.address:
        try:
            geo_query = f"{payload.address}, {payload.city or ''} {payload.zipcode or ''}".strip()
            geo_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(geo_query)}&format=json&limit=1"
            geo_req = urllib.request.Request(geo_url, headers={"User-Agent": "RestaurantAI/1.0"})
            geo_res = urllib.request.urlopen(geo_req, timeout=10)
            geo_data = _json.loads(geo_res.read())
            if geo_data:
                r_lat = float(geo_data[0]["lat"])
                r_lng = float(geo_data[0]["lon"])
        except Exception:
            pass  # Keep original values if geocoding fails

    r = models.Restaurant(
        owner_id=current_user.id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        city=payload.city,
        address=payload.address,
        zipcode=payload.zipcode,
        latitude=r_lat,
        longitude=r_lng,
        phone=payload.phone,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@app.put("/owner/restaurants/{restaurant_id}", response_model=schemas.RestaurantOut)
def update_restaurant(restaurant_id: int, payload: schemas.RestaurantUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    r = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id, models.Restaurant.owner_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return r


# --- Categories ---
@app.post("/owner/restaurants/{restaurant_id}/categories", response_model=schemas.MenuCategoryOut)
def create_category(restaurant_id: int, payload: schemas.CategoryCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    r = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id, models.Restaurant.owner_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    c = models.MenuCategory(restaurant_id=restaurant_id, name=payload.name, sort_order=payload.sort_order)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@app.put("/owner/categories/{category_id}", response_model=schemas.MenuCategoryOut)
def update_category(category_id: int, payload: schemas.CategoryUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    c = db.query(models.MenuCategory).join(models.Restaurant).filter(models.MenuCategory.id == category_id, models.Restaurant.owner_id == current_user.id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Category not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


@app.delete("/owner/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    c = db.query(models.MenuCategory).join(models.Restaurant).filter(models.MenuCategory.id == category_id, models.Restaurant.owner_id == current_user.id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# --- Menu Items ---
@app.post("/owner/categories/{category_id}/items", response_model=schemas.MenuItemOut)
def create_item(category_id: int, payload: schemas.ItemCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    c = db.query(models.MenuCategory).join(models.Restaurant).filter(models.MenuCategory.id == category_id, models.Restaurant.owner_id == current_user.id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Category not found")
    tags_json = _json.dumps(payload.tags) if payload.tags else None
    item = models.MenuItem(
        category_id=category_id,
        name=payload.name,
        description=payload.description,
        price_cents=payload.price_cents,
        is_available=payload.is_available,
        portion_people=payload.portion_people,
        cuisine=payload.cuisine,
        protein_type=payload.protein_type,
        tags=tags_json,
        calories=payload.calories,
        prep_time_mins=payload.prep_time_mins,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.put("/owner/items/{item_id}", response_model=schemas.MenuItemOut)
def update_item(item_id: int, payload: schemas.ItemUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    item = db.query(models.MenuItem).join(models.MenuCategory).join(models.Restaurant).filter(models.MenuItem.id == item_id, models.Restaurant.owner_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if k == "tags":
            setattr(item, k, _json.dumps(v) if v else None)
        else:
            setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/owner/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    item = db.query(models.MenuItem).join(models.MenuCategory).join(models.Restaurant).filter(models.MenuItem.id == item_id, models.Restaurant.owner_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


# --- Owner: View orders ---
@app.get("/owner/restaurants/{restaurant_id}/orders")
def owner_orders(
    restaurant_id: int,
    status: str | None = None,
    exclude_status: str | None = "completed,rejected",
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get active orders. By default excludes completed and rejected orders for fast loading."""
    r = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id, models.Restaurant.owner_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    q = db.query(models.Order).filter(models.Order.restaurant_id == restaurant_id)
    if status:
        q = q.filter(models.Order.status == status)
    elif exclude_status:
        excluded = [s.strip() for s in exclude_status.split(",") if s.strip()]
        if excluded:
            q = q.filter(~models.Order.status.in_(excluded))
    q = _apply_order_filters(q, db, search, date_from, date_to)
    orders = q.order_by(models.Order.created_at.desc()).limit(50).all()
    return _serialize_orders(db, orders)


@app.get("/owner/restaurants/{restaurant_id}/orders/archived")
def owner_orders_archived(
    restaurant_id: int,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get archived (completed/rejected) orders with pagination."""
    r = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id, models.Restaurant.owner_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    q = db.query(models.Order).filter(
        models.Order.restaurant_id == restaurant_id,
        models.Order.status.in_(["completed", "rejected"]),
    )
    q = _apply_order_filters(q, db, search, date_from, date_to)
    total = q.count()
    orders = q.order_by(models.Order.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "orders": _serialize_orders(db, orders),
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if per_page else 1,
    }


@app.get("/owner/restaurants/{restaurant_id}/complaints")
def owner_complaints(
    restaurant_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List escalated customer feedback (rating <= 2) for restaurant dashboard."""
    r = db.query(models.Restaurant).filter(
        models.Restaurant.id == restaurant_id,
        models.Restaurant.owner_id == current_user.id,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return crud.list_complaints_for_restaurant(db, restaurant_id)


def _apply_order_filters(q, db, search, date_from, date_to):
    """Apply search and date filters to an orders query."""
    from datetime import datetime, timedelta
    # Date filters
    if date_from:
        try:
            d = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(models.Order.created_at >= d)
        except ValueError:
            pass
    if date_to:
        try:
            d = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            q = q.filter(models.Order.created_at < d)
        except ValueError:
            pass
    # Search filter: order ID, customer email, or item names
    if search and search.strip():
        s = search.strip().lower()
        # Try order ID match
        try:
            order_id = int(s.replace("#", ""))
            q = q.filter(models.Order.id == order_id)
        except ValueError:
            # Search by customer email or item names
            # Get user IDs matching search
            matching_users = db.query(models.User.id).filter(
                models.User.email.ilike(f"%{s}%")
            ).all()
            user_ids = [u.id for u in matching_users]
            # Get order IDs with matching item names
            matching_orders = db.query(models.OrderItem.order_id).join(
                models.MenuItem, models.OrderItem.menu_item_id == models.MenuItem.id
            ).filter(
                models.MenuItem.name.ilike(f"%{s}%")
            ).distinct().all()
            order_ids = [o.order_id for o in matching_orders]
            from sqlalchemy import or_
            conditions = []
            if user_ids:
                conditions.append(models.Order.user_id.in_(user_ids))
            if order_ids:
                conditions.append(models.Order.id.in_(order_ids))
            if conditions:
                q = q.filter(or_(*conditions))
            else:
                # No matches — return empty
                q = q.filter(models.Order.id == -1)
    return q


def _serialize_orders(db, orders):
    """Serialize a list of Order objects to dicts."""
    # Batch-load all menu item IDs + user IDs to avoid N+1 queries
    item_ids = set()
    user_ids = set()
    for o in orders:
        user_ids.add(o.user_id)
        for oi in o.items:
            item_ids.add(oi.menu_item_id)

    menu_items = {}
    if item_ids:
        for mi in db.query(models.MenuItem).filter(models.MenuItem.id.in_(item_ids)).all():
            menu_items[mi.id] = mi.name

    users = {}
    if user_ids:
        for u in db.query(models.User).filter(models.User.id.in_(user_ids)).all():
            users[u.id] = u.email

    results = []
    for o in orders:
        items = []
        for oi in o.items:
            items.append({
                "name": menu_items.get(oi.menu_item_id, "?"),
                "quantity": oi.quantity,
                "price_cents": oi.price_cents,
            })
        results.append({
            "id": o.id,
            "status": o.status,
            "total_cents": o.total_cents,
            "created_at": o.created_at.isoformat(),
            "customer_email": users.get(o.user_id),
            "items": items,
        })
    return results

# --- Owner: Sales Analytics ---
@app.get("/owner/restaurants/{restaurant_id}/analytics")
def owner_analytics(
    restaurant_id: int,
    period: str = "month",  # week, month, year, custom
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Sales analytics for a restaurant."""
    from datetime import datetime, timedelta
    from sqlalchemy import func, desc

    r = db.query(models.Restaurant).filter(
        models.Restaurant.id == restaurant_id,
        models.Restaurant.owner_id == current_user.id,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # Determine date range
    now = datetime.utcnow()
    if period == "week":
        start = now - timedelta(days=7)
        end = now
    elif period == "month":
        start = now - timedelta(days=30)
        end = now
    elif period == "year":
        start = now - timedelta(days=365)
        end = now
    elif period == "custom" and date_from:
        try:
            start = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            start = now - timedelta(days=30)
        try:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1) if date_to else now
        except ValueError:
            end = now
    else:
        start = now - timedelta(days=30)
        end = now

    # Only completed orders count as sales
    base_q = db.query(models.Order).filter(
        models.Order.restaurant_id == restaurant_id,
        models.Order.status == "completed",
        models.Order.created_at >= start,
        models.Order.created_at < end,
    )

    # Summary stats
    orders = base_q.all()
    total_revenue = sum(o.total_cents for o in orders)
    order_count = len(orders)
    avg_order = total_revenue // order_count if order_count else 0

    # Daily revenue for chart
    daily = {}
    for o in orders:
        day = o.created_at.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = {"date": day, "revenue": 0, "orders": 0}
        daily[day]["revenue"] += o.total_cents
        daily[day]["orders"] += 1

    # Fill in missing days with zero
    day_cursor = start
    while day_cursor < end:
        day_str = day_cursor.strftime("%Y-%m-%d")
        if day_str not in daily:
            daily[day_str] = {"date": day_str, "revenue": 0, "orders": 0}
        day_cursor += timedelta(days=1)

    daily_revenue = sorted(daily.values(), key=lambda x: x["date"])

    # Top selling items
    item_sales = {}
    for o in orders:
        for oi in o.items:
            mid = oi.menu_item_id
            if mid not in item_sales:
                item_sales[mid] = {"menu_item_id": mid, "quantity": 0, "revenue": 0}
            item_sales[mid]["quantity"] += oi.quantity
            item_sales[mid]["revenue"] += oi.price_cents * oi.quantity

    # Get menu item names
    item_ids = list(item_sales.keys())
    mi_names = {}
    if item_ids:
        for mi in db.query(models.MenuItem).filter(models.MenuItem.id.in_(item_ids)).all():
            mi_names[mi.id] = mi.name

    top_items = sorted(item_sales.values(), key=lambda x: x["quantity"], reverse=True)[:10]
    for t in top_items:
        t["name"] = mi_names.get(t["menu_item_id"], "Unknown")

    # Orders by status (all statuses in the time range)
    all_orders_in_range = db.query(models.Order).filter(
        models.Order.restaurant_id == restaurant_id,
        models.Order.created_at >= start,
        models.Order.created_at < end,
    ).all()
    status_counts = {}
    for o in all_orders_in_range:
        status_counts[o.status] = status_counts.get(o.status, 0) + 1

    return {
        "period": period,
        "date_from": start.strftime("%Y-%m-%d"),
        "date_to": end.strftime("%Y-%m-%d"),
        "summary": {
            "total_revenue_cents": total_revenue,
            "order_count": order_count,
            "avg_order_cents": avg_order,
        },
        "daily_revenue": daily_revenue,
        "top_items": top_items,
        "orders_by_status": status_counts,
    }


# --- Owner: Update order status ---
@app.patch("/owner/orders/{order_id}/status")
def update_order_status(order_id: int, payload: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    from datetime import datetime, timedelta

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Verify ownership
    rest = db.query(models.Restaurant).filter(
        models.Restaurant.id == order.restaurant_id,
        models.Restaurant.owner_id == current_user.id
    ).first()
    if not rest:
        raise HTTPException(status_code=403, detail="Not your restaurant")
    new_status = payload.get("status", "")
    valid = ["accepted", "rejected", "preparing", "ready", "completed"]
    if new_status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {valid}")

    now = datetime.utcnow()
    order.status = new_status
    order.status_updated_at = now

    # When preparing starts, set ETA
    if new_status == "preparing":
        prep_mins = rest.avg_prep_minutes or 20
        order.estimated_ready_at = now + timedelta(minutes=prep_mins)

    # When ready/completed, clear ETA and auto-adjust restaurant avg prep time
    if new_status in ("ready", "completed"):
        order.estimated_ready_at = None
        # Calculate actual prep time and update rolling average
        if order.status_updated_at:
            # Find when "preparing" started by looking at recent history
            # For simplicity, use time since last status change
            pass  # Will be refined when we have status history

    db.commit()
    return {"ok": True, "order_id": order_id, "status": new_status,
            "estimated_ready_at": order.estimated_ready_at.isoformat() if order.estimated_ready_at else None}


# --- Customer: Track order progress ---
@app.get("/orders/{order_id}/track")
def track_order(order_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Get real-time tracking info for a customer's order."""
    from datetime import datetime

    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.user_id == current_user.id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Queue position: count of orders ahead at same restaurant
    active_statuses = ["confirmed", "accepted", "preparing"]
    if order.status in active_statuses:
        queue_position = db.query(models.Order).filter(
            models.Order.restaurant_id == order.restaurant_id,
            models.Order.status.in_(active_statuses),
            models.Order.created_at < order.created_at,
            models.Order.id != order.id,
        ).count() + 1  # +1 for this order's position
    else:
        queue_position = 0

    # Build progress steps
    STATUS_STEPS = [
        ("confirmed", "Order Confirmed"),
        ("accepted", "Accepted"),
        ("preparing", "Preparing"),
        ("ready", "Ready for Pickup"),
        ("completed", "Picked Up"),
    ]
    status_order = [s[0] for s in STATUS_STEPS]
    current_idx = status_order.index(order.status) if order.status in status_order else -1

    steps = []
    for i, (status_key, label) in enumerate(STATUS_STEPS):
        if i < current_idx:
            step_status = "done"
        elif i == current_idx:
            step_status = "active"
        else:
            step_status = "upcoming"
        steps.append({"name": label, "key": status_key, "status": step_status})

    # ETA
    now = datetime.utcnow()
    eta_minutes = None
    if order.estimated_ready_at and order.estimated_ready_at > now:
        eta_minutes = int((order.estimated_ready_at - now).total_seconds() / 60)

    # Elapsed since order placed
    elapsed_minutes = int((now - order.created_at).total_seconds() / 60)

    # Restaurant info
    rest = db.query(models.Restaurant).filter(models.Restaurant.id == order.restaurant_id).first()

    return {
        "order_id": order.id,
        "status": order.status,
        "queue_position": queue_position,
        "estimated_ready_at": order.estimated_ready_at.isoformat() if order.estimated_ready_at else None,
        "eta_minutes": eta_minutes,
        "elapsed_minutes": elapsed_minutes,
        "steps": steps,
        "restaurant_name": rest.name if rest else "Unknown",
        "total_cents": order.total_cents,
        "created_at": order.created_at.isoformat(),
    }


# --- Public: Restaurant kitchen queue info ---
@app.get("/restaurant/{restaurant_id}/queue")
def restaurant_queue(restaurant_id: int, db: Session = Depends(get_db)):
    """Get current kitchen load for a restaurant (shown on restaurant cards)."""
    rest = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id).first()
    if not rest:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    active_statuses = ["confirmed", "accepted", "preparing"]
    active_count = db.query(models.Order).filter(
        models.Order.restaurant_id == restaurant_id,
        models.Order.status.in_(active_statuses),
    ).count()

    avg_wait = rest.avg_prep_minutes or 20
    # Estimate total wait = avg_prep * ceil(active_orders / 2) (assuming 2 parallel orders)
    estimated_wait = avg_wait * max(1, (active_count + 1) // 2) if active_count > 0 else 0

    return {
        "restaurant_id": restaurant_id,
        "active_orders": active_count,
        "avg_prep_minutes": avg_wait,
        "estimated_wait_minutes": estimated_wait,
    }


# --- Owner: Update notification settings ---
@app.patch("/owner/restaurants/{restaurant_id}/notifications")
def update_notifications(restaurant_id: int, payload: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    r = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id, models.Restaurant.owner_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if "notification_email" in payload:
        r.notification_email = payload["notification_email"]
    if "notification_phone" in payload:
        r.notification_phone = payload["notification_phone"]
    db.commit()
    return {"ok": True}


# --- Multi-channel notification helpers ---

def _build_notification_message(restaurant, order, items, customer_email):
    """Build the notification text shared across all channels."""
    items_text = "\n".join([f"  • {i['name']} x{i['quantity']} — ${i['price_cents']/100:.2f}" for i in items])
    total = f"${order.total_cents/100:.2f}"
    return f"""🔔 New Order #{order.id} — {restaurant.name}

👤 Customer: {customer_email}
💰 Total: {total}

Items:
{items_text}

Log in to your Owner Dashboard to accept or reject this order."""


def _send_email_notification(restaurant, order, items, customer_email, db):
    """Send email notification to restaurant owner about new order."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    load_dotenv()
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")

    to_email = restaurant.notification_email
    if not to_email:
        owner = db.query(models.User).get(restaurant.owner_id)
        to_email = owner.email if owner else None

    if not to_email or not smtp_user:
        print(f"[Notification] Email skipped — no recipient or SMTP config")
        return

    body = _build_notification_message(restaurant, order, items, customer_email)
    subject = f"🔔 New Order #{order.id} — {restaurant.name}"

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        print(f"[Notification] ✅ Email sent to {to_email} for order #{order.id}")
    except Exception as e:
        print(f"[Notification] ❌ Email failed: {e}")


def _send_sms_notification(restaurant, order, items, customer_email, db):
    """Send SMS notification via Twilio REST API."""
    load_dotenv()
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "")

    to_phone = restaurant.notification_phone
    if not to_phone:
        print(f"[Notification] SMS skipped — no phone number configured")
        return

    if not account_sid or account_sid == "your_account_sid_here":
        print(f"[Notification] SMS skipped — Twilio credentials not configured")
        return

    # Short message for SMS (trial accounts limited to 160 chars / single segment)
    item_count = sum(i['quantity'] for i in items)
    total = order.total_cents / 100
    body = "New Order #{} - {} item(s) ${:.2f} from {}. Check your dashboard.".format(
        order.id, item_count, total, customer_email.split('@')[0]
    )
    if len(body) > 155:
        body = body[:152] + "..."

    try:
        import base64
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        data = urllib.parse.urlencode({
            "To": to_phone,
            "From": from_number,
            "Body": body,
        }).encode()

        credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        req = urllib.request.Request(url, data, {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        res = urllib.request.urlopen(req, timeout=30)
        result = _json.loads(res.read())
        print(f"[Notification] ✅ SMS sent to {to_phone} — SID: {result.get('sid', '?')}")
    except Exception as e:
        print(f"[Notification] ❌ SMS failed: {e}")


def _send_whatsapp_notification(restaurant, order, items, customer_email, db):
    """Send WhatsApp notification via Twilio WhatsApp API."""
    load_dotenv()
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_whatsapp = os.getenv("TWILIO_WHATSAPP_NUMBER", "")

    to_phone = restaurant.notification_phone
    if not to_phone:
        print(f"[Notification] WhatsApp skipped — no phone number configured")
        return

    if not account_sid or account_sid == "your_account_sid_here":
        print(f"[Notification] WhatsApp skipped — Twilio credentials not configured")
        return

    body = _build_notification_message(restaurant, order, items, customer_email)

    try:
        import base64
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        data = urllib.parse.urlencode({
            "To": f"whatsapp:{to_phone}",
            "From": f"whatsapp:{from_whatsapp}",
            "Body": body,
        }).encode()

        credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        req = urllib.request.Request(url, data, {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        res = urllib.request.urlopen(req, timeout=30)
        result = _json.loads(res.read())
        print(f"[Notification] ✅ WhatsApp sent to {to_phone} — SID: {result.get('sid', '?')}")
    except Exception as e:
        print(f"[Notification] ❌ WhatsApp failed: {e}")


def _send_all_notifications(restaurant, order, items, customer_email, db):
    """Dispatch all notification channels. Each channel is independent — one failure won't block others.
    Phase 1: All 3 fire on every order for testing.
    Phase 2: Respect owner preferences (email/sms/whatsapp toggles).
    """
    print(f"[Notification] === Sending notifications for Order #{order.id} ({restaurant.name}) ===")

    # Channel 1: Email
    try:
        _send_email_notification(restaurant, order, items, customer_email, db)
    except Exception as e:
        print(f"[Notification] Email channel error: {e}")

    # Channel 2: SMS
    try:
        _send_sms_notification(restaurant, order, items, customer_email, db)
    except Exception as e:
        print(f"[Notification] SMS channel error: {e}")

    # Channel 3: WhatsApp
    try:
        _send_whatsapp_notification(restaurant, order, items, customer_email, db)
    except Exception as e:
        print(f"[Notification] WhatsApp channel error: {e}")

    print(f"[Notification] === Done for Order #{order.id} ===")


# --- Customer: Checkout ---
@app.post("/checkout")
def checkout(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Confirm all pending orders in cart. Triggers notifications to restaurants."""
    pending_orders = db.query(models.Order).filter(
        models.Order.user_id == current_user.id,
        models.Order.status == "pending"
    ).all()

    if not pending_orders:
        raise HTTPException(status_code=400, detail="No items in cart")

    confirmed = []
    for order in pending_orders:
        order.status = "confirmed"
        db.commit()

        # Build items list for notification
        rest = db.query(models.Restaurant).get(order.restaurant_id)
        items = []
        for oi in order.items:
            mi = db.query(models.MenuItem).get(oi.menu_item_id)
            items.append({"name": mi.name if mi else "?", "quantity": oi.quantity, "price_cents": oi.price_cents})

        confirmed.append({
            "order_id": order.id,
            "restaurant": rest.name if rest else "?",
            "total_cents": order.total_cents,
            "items": items,
        })

        # Send notifications (email + SMS + WhatsApp)
        if rest:
            try:
                _send_all_notifications(rest, order, items, current_user.email, db)
            except Exception as e:
                print(f"[Notification] Failed for order {order.id}: {e}")

    return {"ok": True, "orders": confirmed, "count": len(confirmed)}


# =============================================================
# Payment Integration (Stripe)
# =============================================================

# --- Owner: Start Free Trial ---
@app.post("/owner/start-trial")
def owner_start_trial(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Start a 30-day free trial for a restaurant owner."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")
    sub = payments.start_free_trial(db, current_user)
    return {
        "ok": True,
        "plan": sub.plan,
        "status": sub.status,
        "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
    }


# --- Owner: Subscribe to a plan ---
@app.post("/owner/subscribe")
def owner_subscribe(
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a Stripe Checkout Session for owner subscription."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")
    plan = payload.get("plan", "standard")
    result = payments.create_subscription_checkout(db, current_user, plan)
    return result


# --- Owner: Get subscription status ---
@app.get("/owner/subscription")
def owner_subscription_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get the current owner's subscription status. Auto-expires trials past 30 days."""
    sub = payments.get_subscription(db, current_user.id)
    if not sub:
        return {"plan": None, "status": "none", "active": False}
    # Auto-expire trial if past due
    sub = payments.check_and_expire_trial(db, sub)
    days_remaining = payments.get_trial_days_remaining(sub)
    return {
        "id": sub.id,
        "plan": sub.plan,
        "status": sub.status,
        "active": payments.is_subscription_active(sub),
        "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
        "trial_expired": sub.status == "expired",
        "days_remaining": days_remaining,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
    }


# --- Owner: Manage billing (Stripe Customer Portal) ---
@app.post("/owner/manage-billing")
def owner_manage_billing(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a Stripe Customer Portal session."""
    url = payments.create_billing_portal(db, current_user)
    return {"url": url}


# --- Customer: Create checkout session ---
@app.post("/checkout/create-session")
def create_checkout_session(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a Stripe Checkout Session for cart items."""
    result = payments.create_order_checkout(db, current_user)
    # If dev-mode (simulated), trigger notifications like regular checkout
    if result.get("session_id") == "sim_dev" and result.get("orders"):
        for order_info in result["orders"]:
            order = db.query(models.Order).filter(models.Order.id == order_info["order_id"]).first()
            rest = db.query(models.Restaurant).filter(models.Restaurant.id == order.restaurant_id).first() if order else None
            if rest and order:
                try:
                    _send_all_notifications(rest, order, order_info["items"], current_user.email, db)
                except Exception as e:
                    print(f"[Notification] Failed for order {order.id}: {e}")
    return result


@app.post("/checkout/verify")
def verify_checkout_payment(
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Verify a Stripe checkout session and confirm orders if paid.
    Called by the frontend after Stripe redirects back with a session_id.
    """
    session_id = payload.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Dev mode — orders already confirmed by _simulate_order_checkout
    if session_id == "sim_dev":
        orders = db.query(models.Order).filter(
            models.Order.user_id == current_user.id,
            models.Order.status != "pending",
        ).order_by(models.Order.created_at.desc()).limit(5).all()
        return {"ok": True, "status": "paid", "orders": [
            {"order_id": o.id, "status": o.status, "total_cents": o.total_cents}
            for o in orders
        ]}

    # Real Stripe — retrieve the session and verify
    import stripe as stripe_lib
    try:
        session = stripe_lib.checkout.Session.retrieve(session_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid session: {str(e)}")

    if session.payment_status != "paid":
        return {"ok": False, "status": session.payment_status, "orders": []}

    # Payment confirmed — update orders
    metadata = session.get("metadata", {})
    order_ids_str = metadata.get("order_ids", "")
    order_ids = [int(x) for x in order_ids_str.split(",") if x]

    confirmed = []
    for oid in order_ids:
        order = db.query(models.Order).filter(
            models.Order.id == oid,
            models.Order.user_id == current_user.id
        ).first()
        if order and order.status == "pending":
            order.status = "confirmed"
            confirmed.append({"order_id": order.id, "status": "confirmed", "total_cents": order.total_cents})

            # Send notifications
            rest = db.query(models.Restaurant).filter(models.Restaurant.id == order.restaurant_id).first()
            if rest:
                items = []
                for oi in order.items:
                    mi = db.query(models.MenuItem).filter(models.MenuItem.id == oi.menu_item_id).first()
                    items.append({"name": mi.name if mi else "?", "quantity": oi.quantity, "price_cents": oi.price_cents})
                try:
                    _send_all_notifications(rest, order, items, current_user.email, db)
                except Exception as e:
                    print(f"[Notification] Failed for order {order.id}: {e}")
        elif order:
            confirmed.append({"order_id": order.id, "status": order.status, "total_cents": order.total_cents})
    db.commit()

    # Update payment record
    payment_rec = db.query(models.Payment).filter(
        models.Payment.stripe_checkout_session_id == session_id
    ).first()
    if payment_rec:
        payment_rec.status = "completed"
        payment_rec.stripe_payment_intent_id = session.get("payment_intent", "")
        db.commit()

    return {"ok": True, "status": "paid", "orders": confirmed}



# --- Stripe Webhook ---
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    return payments.handle_stripe_webhook(payload, sig_header, db)



# --- Customer: My Orders (track status) ---
def _order_feedback_eligible(o) -> bool:
    """Eligible for feedback: completed and at least 30 min since status_updated_at (proxy for delivered)."""
    if o.status != "completed":
        return False
    from datetime import datetime
    updated = o.status_updated_at or o.created_at
    if not updated:
        return False
    now = datetime.utcnow()
    try:
        delta_seconds = (now - updated).total_seconds()
    except TypeError:
        return False
    return delta_seconds >= (30 * 60)


@app.get("/my-orders")
def my_orders(db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    """Get all non-pending orders for the current customer, newest first. Returns [] when not logged in."""
    if current_user is None:
        return []
    try:
        orders = db.query(models.Order).filter(
            models.Order.user_id == current_user.id,
            models.Order.status != "pending"
        ).order_by(models.Order.created_at.desc()).limit(20).all()
    except Exception:
        return []
    results = []
    active_statuses = ["confirmed", "accepted", "preparing"]
    for o in orders:
        try:
            rest = db.query(models.Restaurant).filter(models.Restaurant.id == o.restaurant_id).first()
            items = []
            for oi in o.items:
                mi = db.query(models.MenuItem).filter(models.MenuItem.id == oi.menu_item_id).first()
                items.append({
                    "name": mi.name if mi else "?",
                    "quantity": getattr(oi, "quantity", 0),
                    "price_cents": getattr(oi, "price_cents", 0),
                })

            queue_position = 0
            if o.status in active_statuses and getattr(o, "created_at", None) is not None:
                queue_position = db.query(models.Order).filter(
                    models.Order.restaurant_id == o.restaurant_id,
                    models.Order.status.in_(active_statuses),
                    models.Order.created_at < o.created_at,
                    models.Order.id != o.id,
                ).count() + 1

            feedback = crud.get_feedback_by_order(db, o.id)
            feedback_eligible = _order_feedback_eligible(o) and feedback is None

            created_at = o.created_at.isoformat() if getattr(o, "created_at", None) else None
            estimated_ready_at = o.estimated_ready_at.isoformat() if getattr(o, "estimated_ready_at", None) else None
            status_updated_at = o.status_updated_at.isoformat() if getattr(o, "status_updated_at", None) else None
            results.append({
                "id": o.id,
                "status": o.status,
                "total_cents": getattr(o, "total_cents", 0),
                "created_at": created_at,
                "restaurant_name": rest.name if rest else "?",
                "restaurant_id": o.restaurant_id,
                "items": items,
                "estimated_ready_at": estimated_ready_at,
                "status_updated_at": status_updated_at,
                "queue_position": queue_position,
                "feedback_eligible": feedback_eligible,
                "feedback": {"id": feedback.id, "rating": feedback.rating} if feedback else None,
            })
        except Exception:
            continue
    return results


# --- Post-Order Feedback ---
@app.post("/feedback", response_model=schemas.FeedbackOut)
def submit_feedback(
    payload: schemas.FeedbackCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Submit post-order feedback. Order must be completed, belong to user, and not already have feedback."""
    order = crud.get_order(db, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your order")
    if order.status != "completed":
        raise HTTPException(status_code=400, detail="Can only give feedback for completed orders")
    if crud.get_feedback_by_order(db, order.id):
        raise HTTPException(status_code=400, detail="Feedback already submitted for this order")
    fb = crud.create_feedback(
        db, current_user.id, payload.order_id, payload.rating,
        issues=payload.issues, comment=payload.comment,
    )
    import json
    return schemas.FeedbackOut(
        id=fb.id,
        order_id=fb.order_id,
        rating=fb.rating,
        issues=json.loads(fb.issues) if fb.issues else [],
        comment=fb.comment,
        photo_url=fb.photo_url,
        created_at=fb.created_at,
        escalated=fb.rating <= 2,
    )


@app.get("/orders/{order_id}/feedback")
def get_order_feedback(
    order_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get feedback for an order (owner or the customer who placed it)."""
    order = crud.get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != current_user.id and current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    fb = crud.get_feedback_by_order(db, order_id)
    if not fb:
        return None
    import json
    return {
        "id": fb.id,
        "order_id": fb.order_id,
        "rating": fb.rating,
        "issues": json.loads(fb.issues) if fb.issues else [],
        "comment": fb.comment,
        "photo_url": fb.photo_url,
        "created_at": fb.created_at.isoformat(),
        "escalated": fb.rating <= 2,
    }


# --- Group Ordering ---

@app.post("/group/session", response_model=schemas.GroupOrderSessionOut)
def create_group_session(
    payload: schemas.GroupOrderSessionCreate | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    """Create a new group order session. Returns share_code and share link. Auth optional."""
    payload = payload or schemas.GroupOrderSessionCreate()
    session = crud.create_group_order_session(
        db,
        creator_user_id=current_user.id if current_user else None,
        delivery_zipcode=payload.delivery_zipcode,
    )
    members_out = [
        schemas.GroupOrderMemberOut(
            id=m.id,
            name=m.name,
            preference=m.preference,
            budget_cents=m.budget_cents,
            dietary_restrictions=m.dietary_restrictions,
        )
        for m in session.members
    ]
    return schemas.GroupOrderSessionOut(
        id=session.id,
        share_code=session.share_code,
        status=session.status,
        delivery_address_zipcode=session.delivery_address_zipcode,
        created_at=session.created_at,
        members=members_out,
    )


@app.get("/group/{group_id_or_code}", response_model=schemas.GroupOrderSessionOut)
def get_group_session(
    group_id_or_code: str,
    db: Session = Depends(get_db),
):
    """Get group session by id or share code. No auth required (for share link)."""
    session = crud.get_group_session_by_id_or_code(db, group_id_or_code)
    if not session:
        raise HTTPException(status_code=404, detail="Group not found")
    members_out = [
        schemas.GroupOrderMemberOut(
            id=m.id,
            name=m.name,
            preference=m.preference,
            budget_cents=m.budget_cents,
            dietary_restrictions=m.dietary_restrictions,
        )
        for m in session.members
    ]
    return schemas.GroupOrderSessionOut(
        id=session.id,
        share_code=session.share_code,
        status=session.status,
        delivery_address_zipcode=session.delivery_address_zipcode,
        created_at=session.created_at,
        members=members_out,
    )


@app.post("/group/{group_id_or_code}/join", response_model=schemas.GroupOrderMemberOut)
def join_group_session(
    group_id_or_code: str,
    payload: schemas.GroupOrderMemberIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    """Join a group order: add yourself (name, preference, budget, dietary). No auth required."""
    session = crud.get_group_session_by_id_or_code(db, group_id_or_code)
    if not session:
        raise HTTPException(status_code=404, detail="Group not found")
    if session.status != "active":
        raise HTTPException(status_code=400, detail="Group order is no longer active")
    member = crud.add_group_member(
        db,
        session.id,
        name=payload.name,
        preference=payload.preference,
        budget_cents=payload.budget_cents,
        dietary_restrictions=payload.dietary_restrictions,
        user_id=current_user.id if current_user else None,
    )
    return schemas.GroupOrderMemberOut(
        id=member.id,
        name=member.name,
        preference=member.preference,
        budget_cents=member.budget_cents,
        dietary_restrictions=member.dietary_restrictions,
    )


@app.get("/group/{group_id_or_code}/recommendation", response_model=schemas.GroupOrderRecommendationOut)
def get_group_recommendation(
    group_id_or_code: str,
    lat: float | None = None,
    lng: float | None = None,
    restaurant_ids: str | None = None,
    cuisine: str | None = None,
    db: Session = Depends(get_db),
):
    """Get AI consensus: best restaurant and suggested dishes for the group. No auth required.
    By default searches across all restaurants. Optional: restaurant_ids (comma-separated, e.g. 1,2,3),
    cuisine (e.g. Indian - only restaurants with that cuisine)."""
    session = crud.get_group_session_by_id_or_code(db, group_id_or_code)
    if not session:
        raise HTTPException(status_code=404, detail="Group not found")
    if not session.members:
        raise HTTPException(status_code=400, detail="Add at least one member to get a recommendation")
    ids_list = None
    if restaurant_ids and restaurant_ids.strip():
        try:
            ids_list = [int(x.strip()) for x in restaurant_ids.split(",") if x.strip()]
        except ValueError:
            ids_list = []
        if not ids_list:
            ids_list = None
    result = group_consensus.get_group_recommendation(
        db, session, lat=lat, lng=lng,
        restaurant_ids=ids_list, cuisine=cuisine,
    )
    if not result:
        raise HTTPException(status_code=404, detail="No restaurant found that fits the group preferences")
    return schemas.GroupOrderRecommendationOut(
        restaurant_id=result["restaurant_id"],
        restaurant_name=result["restaurant_name"],
        suggested_items=[schemas.GroupOrderRecommendationItem(**x) for x in result["suggested_items"]],
        total_cents=result["total_cents"],
        estimated_per_person_cents=result["estimated_per_person_cents"],
        reasons=result["reasons"],
        group_discount_message=result.get("group_discount_message"),
    )


class GroupSplitRequest(BaseModel):
    """For item-based split: total, delivery, tax, and per-member item totals."""
    total_cents: int = Field(ge=0)
    delivery_cents: int = Field(ge=0, default=0)
    tax_cents: int = Field(ge=0, default=0)
    mode: str = "equal"  # equal | item
    member_item_cents: list[dict] | None = None  # [{"member_name": "Alex", "item_total_cents": 1400}]


@app.get("/group/{group_id_or_code}/split", response_model=schemas.GroupOrderSplitOut)
def get_group_split(
    group_id_or_code: str,
    total_cents: int,
    delivery_cents: int = 0,
    tax_cents: int = 0,
    mode: str = "equal",
    db: Session = Depends(get_db),
):
    """Get bill split (equal or item-based). For item-based use POST with member_item_cents."""
    session = crud.get_group_session_by_id_or_code(db, group_id_or_code)
    if not session:
        raise HTTPException(status_code=404, detail="Group not found")
    members = list(session.members)
    if not members:
        raise HTTPException(status_code=400, detail="No members in group")
    split_result = group_consensus.compute_group_split(
        total_cents, delivery_cents, tax_cents, members, mode=mode,
    )
    return schemas.GroupOrderSplitOut(
        total_cents=split_result["total_cents"],
        delivery_cents=split_result["delivery_cents"],
        tax_cents=split_result["tax_cents"],
        split_mode=split_result["split_mode"],
        members=[schemas.GroupOrderSplitMember(**m) for m in split_result["members"]],
    )


@app.post("/group/{group_id_or_code}/split", response_model=schemas.GroupOrderSplitOut)
def post_group_split_item_based(
    group_id_or_code: str,
    payload: GroupSplitRequest,
    db: Session = Depends(get_db),
):
    """Get item-based bill split. Body: total_cents, delivery_cents, tax_cents, member_item_cents."""
    session = crud.get_group_session_by_id_or_code(db, group_id_or_code)
    if not session:
        raise HTTPException(status_code=404, detail="Group not found")
    members = list(session.members)
    if not members:
        raise HTTPException(status_code=400, detail="No members in group")
    item_assignments = None
    if payload.mode == "item" and payload.member_item_cents:
        name_to_cents = {x["member_name"]: x["item_total_cents"] for x in payload.member_item_cents}
        item_assignments = [(m.name, name_to_cents.get(m.name, 0)) for m in members]
    split_result = group_consensus.compute_group_split(
        payload.total_cents,
        payload.delivery_cents,
        payload.tax_cents,
        members,
        mode=payload.mode,
        item_assignments=item_assignments,
    )
    return schemas.GroupOrderSplitOut(
        total_cents=split_result["total_cents"],
        delivery_cents=split_result["delivery_cents"],
        tax_cents=split_result["tax_cents"],
        split_mode=split_result["split_mode"],
        members=[schemas.GroupOrderSplitMember(**m) for m in split_result["members"]],
    )


# --- Taste Profile (AI Flavor / Recommendations) ---
def _taste_profile_to_out(profile):
    import json
    return schemas.TasteProfileOut(
        id=profile.id,
        user_id=profile.user_id,
        spice_level=profile.spice_level or "medium",
        diet=profile.diet,
        liked_cuisines=json.loads(profile.liked_cuisines) if profile.liked_cuisines else [],
        disliked_tags=profile.disliked_tags,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@app.get("/taste/profile", response_model=schemas.TasteProfileOut)
def get_taste_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get current user's taste profile. Creates one with defaults if missing."""
    profile = crud.get_taste_profile(db, current_user.id)
    if not profile:
        profile = crud.upsert_taste_profile(db, current_user.id)
    return _taste_profile_to_out(profile)


@app.put("/taste/profile", response_model=schemas.TasteProfileOut)
def update_taste_profile(
    payload: schemas.TasteProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update current user's taste preferences."""
    profile = crud.upsert_taste_profile(
        db,
        current_user.id,
        spice_level=payload.spice_level,
        diet=payload.diet,
        liked_cuisines=payload.liked_cuisines,
        disliked_tags=payload.disliked_tags,
    )
    return _taste_profile_to_out(profile)


@app.get("/taste/history-summary", response_model=schemas.TasteHistorySummaryOut)
def get_taste_history_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Build taste vector from completed orders (cuisine/protein counts, ordered item ids)."""
    return crud.get_order_history_taste_summary(db, current_user.id)


@app.get("/taste/recommendations", response_model=list[schemas.TasteRecommendationOut])
def get_taste_recommendations(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Personalized recommendations based on taste profile and order history."""
    return crud.get_taste_recommendations(db, current_user.id, limit=min(limit, 20))


# --- /me endpoint ---
@app.get("/auth/me", response_model=schemas.UserOut)
def get_me(current_user=Depends(get_current_user)):
    return current_user


# =============================================================
# AI Menu Extraction
# =============================================================

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_DOC_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}
ALLOWED_ALL_EXTS = ALLOWED_IMAGE_EXTS | ALLOWED_DOC_EXTS


@app.post("/owner/restaurants/{restaurant_id}/extract-menu-file")
async def extract_menu_from_file(
    restaurant_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload an image or document (PDF/DOCX/XLSX) and extract menu items using AI."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")

    r = db.query(models.Restaurant).filter(
        models.Restaurant.id == restaurant_id,
        models.Restaurant.owner_id == current_user.id,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # Validate file type
    import os
    ext = os.path.splitext(file.filename or "")[1].lower()
    print(f"[MenuExtract] Received file: {file.filename} (ext={ext}) for restaurant {restaurant_id}")
    if ext not in ALLOWED_ALL_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_ALL_EXTS)}"
        )

    # Read file bytes
    file_bytes = await file.read()
    print(f"[MenuExtract] File size: {len(file_bytes)} bytes ({len(file_bytes)/1024/1024:.1f}MB)")
    if len(file_bytes) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(status_code=400, detail="File too large. Max 20MB.")

    # Route based on file type
    try:
        if ext in ALLOWED_IMAGE_EXTS:
            from .menu_extractor import extract_menu_from_image
            menu_data = extract_menu_from_image(file_bytes, file.filename or "menu.jpg")
        else:
            from .menu_extractor import extract_menu_from_document
            menu_data = extract_menu_from_document(file_bytes, file.filename or "menu.pdf")
    except ValueError as e:
        print(f"[MenuExtract] Extraction error: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    print(f"[MenuExtract] Success: {sum(len(c.get('items', [])) for c in menu_data.get('categories', []))} items extracted")
    return menu_data


def _normalize_menu_import_url(url: str) -> str:
    """Ensure URL has a scheme so Playwright/fetch work (e.g. anjapparindian.com/menu/... -> https://...)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if not parsed.scheme:
        return ("https:" + url) if url.startswith("//") else ("https://" + url)
    return url


def _fallback_extract_menu_from_text(raw_text: str) -> Optional[dict]:
    """When AI fails, extract menu items from text using price patterns. Handles same-line and price-on-next-line."""
    import re
    # Price: $12.99, 12.99, Rs.199, or just digits with 2 decimal places
    price_only_re = re.compile(r"^\s*(?:\$|Rs\.?|₹|€)?\s*(\d+(?:\.\d{1,2})?)\s*$")
    price_anywhere_re = re.compile(r"(?:\$|Rs\.?|₹|€)?\s*(\d+(?:\.\d{1,2})?)(?=\s|$|,)")
    noise = {"menu", "home", "checkout", "cart", "order", "sign in", "login", "search", "add to cart", "view cart"}
    items = []
    seen = set()
    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]

    for i, line in enumerate(lines):
        if len(line) > 300:
            continue
        # Case 1: Line is only a price (e.g. "14.99" or "$12.99") — use previous line as name
        only_price = price_only_re.match(line)
        if only_price:
            price_val = float(only_price.group(1))
            price_cents = int(round(price_val * 100))
            if price_cents <= 0 or price_cents > 100000:
                continue
            name_part = (lines[i - 1].strip() if i > 0 else "").strip().rstrip(".- ,")
            if not name_part or len(name_part) < 2:
                continue
            lower = name_part.lower()
            if lower in noise or any(lower.startswith(n) for n in ("subtotal", "total", "tax", "delivery")):
                continue
            key = name_part.upper()[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append({"name": name_part[:120], "description": "", "price_cents": price_cents})
            continue

        # Case 2: Price somewhere in the line — find last price match (most likely the item price)
        matches = list(price_anywhere_re.finditer(line))
        if not matches:
            continue
        last_match = matches[-1]
        price_val = float(last_match.group(1))
        price_cents = int(round(price_val * 100))
        if price_cents <= 0 or price_cents > 100000:
            continue
        name_part = line[: last_match.start()].strip().rstrip(".- ,")
        if not name_part or len(name_part) < 2:
            continue
        lower = name_part.lower()
        if lower in noise or any(lower.startswith(n) for n in ("subtotal", "total", "tax", "delivery")):
            continue
        key = name_part.upper()[:80]
        if key in seen:
            continue
        seen.add(key)
        items.append({"name": name_part[:120], "description": "", "price_cents": price_cents})

    if not items:
        return None
    return {
        "restaurant_name": "Extracted",
        "categories": [{"name": "Menu", "items": items}],
    }


@app.post("/owner/import-menu")
def import_menu_from_url(
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Scrape a restaurant website and extract menu using AI. Uses JS rendering for full extraction."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")

    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    url = _normalize_menu_import_url(url)

    from urllib.parse import urljoin, urlparse
    import re

    # Track domains blocked by Cloudflare to skip Playwright for subsequent URLs
    cloudflare_blocked_domains = set()

    def _fetch_rendered(target_url: str) -> str:
        """Fetch a URL with full JS rendering + scrolling + category clicking."""
        from urllib.parse import urlparse as _urlparse
        domain = _urlparse(target_url).netloc

        # Skip Playwright entirely for domains we know are Cloudflare-blocked
        if domain in cloudflare_blocked_domains:
            print(f"[MenuExtract] ⏭️ Skipping Playwright for {domain} (Cloudflare). Using Jina Reader.")
            raise Exception("Cloudflare blocked (cached)")

        # --- Try Playwright first (clicks categories + scrolls for lazy content) ---
        try:
            from playwright.sync_api import sync_playwright
            import time as _time
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                print(f"[MenuExtract] 🌐 Loading {target_url[:80]}...")
                # Use domcontentloaded — networkidle NEVER fires for SPAs (they keep fetching)
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                # Smart wait: SPA pages (ToastTab etc.) render a shell first, then load data
                # Reduced to 7s max — Cloudflare is detectable after 3-4s
                prev_len = 0
                stable_count = 0
                for _wait in range(7):  # Max 7 seconds (was 20)
                    page.wait_for_timeout(1000)
                    curr_len = page.evaluate("document.body.innerText.length")
                    print(f"[MenuExtract]   ... {_wait+1}s: {curr_len} chars")
                    if _wait >= 3 and curr_len > 1000 and curr_len == prev_len:
                        stable_count += 1
                        if stable_count >= 2:
                            break  # Content truly stabilized
                    else:
                        stable_count = 0
                    prev_len = curr_len
                
                # Cloudflare/bot protection detection — bail early if blocked
                page_title = page.title()
                if 'just a moment' in page_title.lower() or curr_len < 500:
                    print(f"[MenuExtract] ⚠️ Cloudflare/bot protection detected (title='{page_title}', {curr_len} chars). Falling back to Jina Reader.")
                    cloudflare_blocked_domains.add(domain)  # Cache for subsequent URLs
                    browser.close()
                    raise Exception("Cloudflare blocked")
                
                print(f"[MenuExtract] ✅ Page loaded ({curr_len} chars of text)")

                # Step 1: Scroll through to trigger initial lazy loading
                prev_height = 0
                for _ in range(30):
                    page.evaluate("window.scrollBy(0, 600)")
                    page.wait_for_timeout(500)
                    curr = page.evaluate("document.body.scrollHeight")
                    if curr == prev_height:
                        break
                    prev_height = curr

                # Step 2: Find and click all category/section nav links
                # Supports: Square/Weebly hash-anchor links, Froogal sidebars,
                # and other SPA frameworks with clickable category navigation.
                try:
                    cat_elements = page.evaluate("""() => {
                        const results = [];
                        const skipTexts = new Set([
                            'HOME', 'MENU', 'MORE', 'CONTACT', 'CONTACT US',
                            'GIFT CARDS', 'SIGN IN', 'ORDER NOW', 'CHECKOUT',
                            'LOGIN', 'ABOUT', 'REWARDS', 'LOCATIONS', 'FRANCHISE',
                            'CATERING', 'PICKUP', 'DELIVERY', 'DINE IN',
                            'SEARCH ANY ITEM', 'TODAY', 'CHANGE',
                        ]);

                        // --- Strategy 1: Hash-anchor links (Square/Weebly) ---
                        document.querySelectorAll('a[href*="#"]').forEach(a => {
                            const text = a.innerText.trim();
                            if (text && text.length > 2 && text.length < 60) {
                                const href = a.getAttribute('href');
                                results.push({selector: `a[href="${href}"]`, text: text});
                            }
                        });

                        // --- Strategy 2: Known sidebar/category selectors ---
                        const sidebarSelectors = [
                            '[class*="category"] a', '[class*="category"] button',
                            '[class*="category"] div[role="button"]',
                            '[class*="sidebar"] a', '[class*="sidebar"] li',
                            '[class*="menu-nav"] a', '[class*="menuNav"] a',
                            '[class*="side-menu"] a', '[class*="sideMenu"] a',
                            '[role="tab"]', '[role="menuitem"]',
                            'nav[class*="menu"] a', 'aside a',
                        ];
                        for (const sel of sidebarSelectors) {
                            document.querySelectorAll(sel).forEach(el => {
                                const text = el.innerText.trim();
                                if (text && text.length > 2 && text.length < 60) {
                                    // Build a unique CSS path for clicking
                                    results.push({selector: null, text: text, tag: el.tagName});
                                }
                            });
                        }

                        // --- Strategy 3: Universal sidebar detection ---
                        // Find vertical lists of short-text clickable items (typical SPA category nav)
                        // Look for containers with many children that have short text
                        const containers = document.querySelectorAll('ul, ol, div, nav, aside');
                        let bestContainer = null;
                        let bestCount = 0;
                        for (const c of containers) {
                            const children = c.children;
                            if (children.length < 5) continue;
                            let menuLike = 0;
                            for (const child of children) {
                                const t = child.innerText.trim();
                                if (t && t.length > 2 && t.length < 60 && t.indexOf(String.fromCharCode(10)) === -1) {
                                    menuLike++;
                                }
                            }
                            // A container where most children are short text = likely category nav
                            if (menuLike > bestCount && menuLike >= 5 && menuLike / children.length > 0.6) {
                                bestCount = menuLike;
                                bestContainer = c;
                            }
                        }
                        if (bestContainer && bestCount > results.length) {
                            // This is likely the sidebar — add its children as candidates
                            results.length = 0;  // Clear previous, this is more reliable
                            for (const child of bestContainer.children) {
                                const t = child.innerText.trim();
                                if (t && t.length > 2 && t.length < 60 && t.indexOf(String.fromCharCode(10)) === -1) {
                                    results.push({selector: null, text: t, tag: child.tagName, fromSidebar: true});
                                }
                            }
                        }

                        // Deduplicate by text
                        const seen = new Set();
                        const unique = [];
                        for (const r of results) {
                            const key = r.text.toUpperCase();
                            if (!seen.has(key) && !skipTexts.has(key)) {
                                seen.add(key);
                                unique.push(r);
                            }
                        }
                        return unique;
                    }""")

                    # Step 2b: Click "More" dropdown first to expose hidden categories
                    try:
                        page.evaluate("""() => {
                            const moreLinks = document.querySelectorAll('a, button, div[role="button"]');
                            for (const el of moreLinks) {
                                const t = el.innerText.trim().toUpperCase();
                                if (t === 'MORE' || t === 'MORE ▾' || t === 'MORE ▼') {
                                    el.click();
                                    break;
                                }
                            }
                        }""")
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass

                    # Click each category element to force-load its items
                    # IMPORTANT: Accumulate text after EACH click because SPA sites
                    # (e.g. Square Online) replace item content on category switch.
                    clicked = set()
                    accumulated_texts = []
                    for cat_info in cat_elements[:40]:  # Cap at 40 categories
                        cat_text = cat_info.get("text", "").strip()
                        cat_upper = cat_text.upper()
                        if cat_upper in clicked:
                            continue
                        if "CATERING" in cat_upper or "PRIVACY" in cat_upper:
                            continue
                        clicked.add(cat_upper)
                        try:
                            selector = cat_info.get("selector")
                            if selector:
                                page.evaluate(f"""() => {{
                                    const el = document.querySelector('{selector}');
                                    if (el) el.click();
                                }}""")
                            else:
                                # Click by matching text content
                                escaped = cat_text.replace("'", "\\'").replace('"', '\\"')
                                page.evaluate(f"""() => {{
                                    // Find element by exact text match
                                    const walker = document.createTreeWalker(
                                        document.body, NodeFilter.SHOW_ELEMENT, null, false
                                    );
                                    let el = walker.nextNode();
                                    while (el) {{
                                        if (el.children.length === 0 || el.children.length === 1) {{
                                            const t = el.innerText.trim();
                                            if (t === "{escaped}") {{
                                                el.click();
                                                break;
                                            }}
                                        }}
                                        el = walker.nextNode();
                                    }}
                                }}""")
                            page.wait_for_timeout(3000)  # Wait for SPA to fetch + render (Square needs 3s)
                            # Scroll content area to trigger lazy rendering within category
                            for _s in range(5):
                                page.evaluate("window.scrollBy(0, 500)")
                                page.wait_for_timeout(300)
                            # Capture ONLY menu content area for this category
                            # (not full page — avoids repeated nav/header/footer in every snapshot)
                            snapshot = page.evaluate("""() => {
                                // Try to find the main content area (skip nav, sidebar, header, footer)
                                const skip = new Set();
                                document.querySelectorAll('nav, header, footer, [class*="sidebar"], [class*="side-bar"], [class*="category-nav"], [class*="categoryNav"]').forEach(el => skip.add(el));
                                // Find the largest content container that's not nav
                                const main = document.querySelector('main, [role="main"], #main-content, .main-content, [class*="order-content"], [class*="menu-content"], [class*="item-list"], [class*="product-list"]');
                                const target = main || document.body;
                                // Get text but skip nav elements
                                let text = '';
                                const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT, null, false);
                                let node = walker.nextNode();
                                while (node) {
                                    let parent = node.parentElement;
                                    let inSkip = false;
                                    while (parent && parent !== target) {
                                        if (skip.has(parent) || parent.tagName === 'NAV' || parent.tagName === 'HEADER' || parent.tagName === 'FOOTER') {
                                            inSkip = true;
                                            break;
                                        }
                                        parent = parent.parentElement;
                                    }
                                    if (!inSkip && node.textContent.trim()) {
                                        text += node.textContent.trim() + '\\n';
                                    }
                                    node = walker.nextNode();
                                }
                                return text;
                            }""")
                            if snapshot and len(snapshot) > 100:
                                accumulated_texts.append(f"=== CATEGORY: {cat_text} ===\n{snapshot}")
                                print(f"[MenuExtract]   📋 Category '{cat_text}': {len(snapshot)} chars captured")
                        except Exception:
                            continue

                except Exception:
                    pass

                # Step 3: Build final text
                if accumulated_texts:
                    # Use accumulated snapshots — this is the key fix for SPA sites
                    # that replace content on each category click (e.g. Square Online)
                    text = "\n\n".join(accumulated_texts)
                    print(f"[MenuExtract] ✅ Accumulated {len(accumulated_texts)} category snapshots ({len(text)} total chars)")
                else:
                    # No categories clicked — do a final full scroll and capture once
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(500)
                    for _ in range(50):
                        page.evaluate("window.scrollBy(0, 600)")
                        page.wait_for_timeout(300)
                        curr = page.evaluate("document.body.scrollHeight")
                        scroll_pos = page.evaluate("window.scrollY + window.innerHeight")
                        if scroll_pos >= curr:
                            break
                    text = page.evaluate("""() => {
                        document.querySelectorAll('script, style, noscript, svg').forEach(el => el.remove());
                        return document.body.innerText;
                    }""")

                browser.close()
                if text and len(text) > 500:
                    return text
        except Exception:
            pass  # Playwright not available or failed

        # --- Fallback: Jina Reader (no scrolling, misses lazy content) ---
        jina_url = f"https://r.jina.ai/{target_url}"
        req = urllib.request.Request(jina_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/plain",
        })
        try:
            response = urllib.request.urlopen(req, timeout=30)
            return response.read().decode("utf-8", errors="ignore")
        except Exception:
            # Fallback to direct HTML fetch
            req2 = urllib.request.Request(target_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            })
            response2 = urllib.request.urlopen(req2, timeout=20)
            html = response2.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "noscript"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)

    def _discover_links_from_text(text: str, base_url: str) -> list:
        """Find menu-related links from rendered markdown text."""
        base_domain = urlparse(base_url).netloc
        menu_keywords = ["menu", "pizza", "burger", "chicken", "pasta",
                        "sandwich", "salad", "appetizer", "dessert", "drink",
                        "beverage", "sides", "entree", "wings", "seafood",
                        "bread", "tots", "specialty", "build-your-own",
                        "steak", "taco", "sushi", "noodle", "curry", "biryani"]
        # Find markdown links: [text](url)
        links = re.findall(r'\[([^\]]*)\]\((https?://[^\)]+)\)', text)
        found = set()
        for link_text, link_url in links:
            parsed = urlparse(link_url)
            if parsed.netloc != base_domain:
                continue
            path = parsed.path.lower().rstrip("/")
            if not path or path == urlparse(base_url).path.lower().rstrip("/"):
                continue
            combined = path + " " + link_text.lower()
            if any(kw in combined for kw in menu_keywords):
                clean = parsed.scheme + "://" + parsed.netloc + parsed.path
                found.add(clean)
        return list(found)[:10]

    # --- Phase 1: Fetch main page with JS rendering ---
    try:
        main_text = _fetch_rendered(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {str(e)}")

    # --- Phase 2: Discover menu sub-pages ---
    menu_links = _discover_links_from_text(main_text, url)
    all_pages = {url: main_text}

    # Also try /menu if not already found
    base = url.rstrip("/")
    if "/menu" not in base.lower():
        menu_url = base + "/menu"
        if menu_url not in all_pages and menu_url not in menu_links:
            menu_links.insert(0, menu_url)

    # --- Phase 3: Crawl discovered category pages ---
    for link in menu_links[:8]:
        if link in all_pages:
            continue
        try:
            page_text = _fetch_rendered(link)
            if len(page_text) > 200:
                all_pages[link] = page_text
        except Exception:
            continue

    # --- Phase 4: Combine all page content (clean navigation cruft) ---
    combined_parts = []
    for page_url, page_text in all_pages.items():
        # Strip markdown links [text](url) — they waste tokens with repeated nav bars
        clean = re.sub(r'\[([^\]]*)\]\(https?://[^\)]+\)', r'\1', page_text)
        # Strip image references
        clean = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', clean)
        # Remove duplicate lines (nav links repeated 3-4 times)
        seen_lines = set()
        deduped = []
        for line in clean.split('\n'):
            stripped = line.strip()
            if stripped and stripped not in seen_lines:
                seen_lines.add(stripped)
                deduped.append(stripped)
            elif not stripped and deduped and deduped[-1] != '':
                deduped.append('')
        clean = '\n'.join(deduped)
        # Remove common non-menu noise
        for noise in ['Shopping Cart', 'Continue Shopping', 'Accepted here',
                       'Secure checkout by Square', 'Back to Cart', 'Sign Up',
                       'reCAPTCHA', 'Privacy Policy', 'Terms of Service',
                       'ALL SALES ARE FINAL', 'Stay in the Loop',
                       'Helpful Information', 'Returns Policy']:
            clean = clean.replace(noise, '')
        # Keep up to 25000 chars per page (large menus need more space)
        clean = clean[:25000]
        if len(clean) > 100:
            label = page_url.split("//", 1)[-1]
            combined_parts.append(f"=== PAGE: {label} ===\n{clean}")

    content = "\n\n".join(combined_parts)
    pages_scraped = len(all_pages)

    if len(content) < 100:
        return {"error": "Could not extract content from this website. Try a direct menu page URL or a food delivery page (DoorDash, UberEats, Grubhub)."}

    # Limit total content for the LLM (raised for large menus like Aroma with 20+ categories)
    content = content[:80000]

    def _parse_menu_json(raw_text):
        """Parse menu JSON from LLM output; handle ```json wrapping and stray text."""
        if not raw_text or not isinstance(raw_text, str):
            return None
        t = raw_text.strip()
        if t.startswith("```"):
            parts = t.split("```", 2)
            if len(parts) >= 2:
                t = parts[1]
                if t.lower().startswith("json"):
                    t = t[4:].lstrip()
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return _json.loads(t[start : end + 1])
            except Exception:
                pass
        try:
            return _json.loads(t)
        except Exception:
            return None

    menu_prompt = f"""Extract the restaurant menu from the following website data.

The data comes from {pages_scraped} page(s) of the same restaurant website.
Each page may contain a different menu category with its items.
Look through ALL pages to find EVERY menu item.

Return JSON with this exact format:
{{
  "restaurant_name": "...",
  "categories": [
    {{
      "name": "Category Name",
      "items": [
        {{
          "name": "Item Name",
          "description": "Short description",
          "price_cents": 1299
        }}
      ]
    }}
  ]
}}

Rules:
- price_cents is the price in cents (e.g. $12.99 = 1299). If no price found, use 0.
- Group items into logical categories (Appetizers, Entrees, Sides, Drinks, Desserts, etc.)
- Keep descriptions short (under 60 chars)
- Extract EVERY single food item you can find from ALL pages
- Look for patterns like "Item Name ... $Price" or "Item Name\\nDescription\\n$Price"
- DO NOT return empty categories. If a category has 0 items, do not include it.
- MERGE items from different pages into unified categories
- Remove navigation text, legal disclaimers, and non-menu content
- If you truly cannot find ANY menu items, return {{"error": "No menu found"}}

Website data:
{content}"""

    # --- Phase 5: Extract with AI (try OpenAI first, then Gemini) ---
    load_dotenv()
    menu_data = None
    response_text = ""

    # Try OpenAI
    oai_key = os.getenv("OPENAI_API_KEY", "")
    if oai_key:
        try:
            oai_url = "https://api.openai.com/v1/chat/completions"
            oai_body = _json.dumps({
                "model": "gpt-4o-mini",
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You extract restaurant menus from website data. Extract EVERY menu item with name, description, and price. Never return empty categories. Return structured JSON."},
                    {"role": "user", "content": menu_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 16000,
            }).encode()

            oai_req = urllib.request.Request(oai_url, oai_body, {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {oai_key}",
            })
            oai_res = urllib.request.urlopen(oai_req, timeout=120)
            oai_data = _json.loads(oai_res.read())
            response_text = oai_data["choices"][0]["message"]["content"].strip()
            menu_data = _parse_menu_json(response_text)
        except Exception as e:
            print(f"[AI] OpenAI extraction error: {e}")
            menu_data = None

    # Count total items extracted
    total_items = 0
    if menu_data and "categories" in menu_data:
        total_items = sum(len(c.get("items", [])) for c in menu_data["categories"])

    # --- Phase 6: Screenshot + Gemini Vision (always run for best results) ---
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"

        def _parse_gemini_json(raw_text):
            """Parse JSON from Gemini response, handling ```json wrapping."""
            t = raw_text.strip()
            if t.startswith("```"):
                t = t.split("```", 2)[1]
                if t.startswith("json"):
                    t = t[4:]
            return _json.loads(t)

        gemini_extraction_prompt = """You are extracting a restaurant menu. Return JSON:
{
  "restaurant_name": "...",
  "categories": [
    {
      "name": "Category Name",
      "items": [{"name": "Dish Name", "description": "brief desc", "price_cents": 1299}]
    }
  ]
}
RULES:
- price_cents = cents ($12.99 → 1299). Use 0 if unknown.
- Every category MUST have items. No empty categories.
- Extract EVERY food item visible, including all categories.
- Include appetizers, mains, sides, drinks, desserts — everything."""

        # --- 6A: Screenshot-based extraction (Gemini Vision) ---
        try:
            # Take a full-page screenshot using thum.io (free, no API key)
            encoded_url = urllib.parse.quote(url, safe='')
            screenshot_url = f"https://image.thum.io/get/width/1280/crop/4000/wait/5/noanimate/{url}"

            ss_req = urllib.request.Request(screenshot_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            ss_res = urllib.request.urlopen(ss_req, timeout=30)
            screenshot_bytes = ss_res.read()

            if len(screenshot_bytes) > 5000:  # Valid image (not an error page)
                import base64
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

                # Determine image type from response headers
                content_type = ss_res.headers.get("Content-Type", "image/png")
                if "jpeg" in content_type or "jpg" in content_type:
                    mime_type = "image/jpeg"
                else:
                    mime_type = "image/png"

                # Send screenshot to Gemini Vision
                vision_body = _json.dumps({
                    "contents": [{
                        "parts": [
                            {"text": f"Look at this restaurant menu page screenshot. {gemini_extraction_prompt}"},
                            {"inline_data": {"mime_type": mime_type, "data": screenshot_b64}}
                        ]
                    }],
                    "generationConfig": {
                        "temperature": 0.1,
                        "responseMimeType": "application/json",
                    }
                }).encode()

                vision_req = urllib.request.Request(gemini_url, vision_body, {
                    "Content-Type": "application/json",
                })
                vision_res = urllib.request.urlopen(vision_req, timeout=120)
                vision_data = _json.loads(vision_res.read())
                vision_text = vision_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                vision_menu = _parse_gemini_json(vision_text)

                vision_items = sum(len(c.get("items", [])) for c in vision_menu.get("categories", []))
                if vision_items > total_items:
                    menu_data = vision_menu
                    total_items = vision_items
        except Exception as e:
            print(f"[AI] Gemini Vision error: {e}")

        # --- 6B: Gemini text (when no menu yet or still low items) ---
        if menu_data is None or total_items < 10:
            try:
                text_prompt = f"""{gemini_extraction_prompt}

Website text content (from {pages_scraped} page(s)):
{content[:30000]}"""

                text_body = _json.dumps({
                    "contents": [{"parts": [{"text": text_prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "responseMimeType": "application/json",
                    }
                }).encode()

                text_req = urllib.request.Request(gemini_url, text_body, {
                    "Content-Type": "application/json",
                })
                text_res = urllib.request.urlopen(text_req, timeout=120)
                text_data = _json.loads(text_res.read())
                text_text = text_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                text_menu = _parse_gemini_json(text_text)
                if text_menu and isinstance(text_menu.get("categories"), list):
                    text_items = sum(len(c.get("items", [])) for c in text_menu.get("categories", []))
                    if text_items > total_items:
                        menu_data = text_menu
                        total_items = text_items
            except Exception as e:
                print(f"[AI] Gemini text error: {e}")

    # --- Fallback: regex-based extraction when AI returned nothing ---
    if not menu_data:
        raw_text = "\n".join(all_pages.values())
        fallback = _fallback_extract_menu_from_text(raw_text)
        if fallback and fallback.get("categories"):
            menu_data = fallback
            print(f"[MenuExtract] Used regex fallback: {sum(len(c.get('items', [])) for c in menu_data['categories'])} items")

    if not menu_data:
        return {"error": f"Could not extract menu from {pages_scraped} page(s). Try a direct menu page URL."}

    # --- Phase 7: Deterministic price fixer ---
    # Scan the ORIGINAL raw text (before cleaning) to build item→price map.
    # The raw text has descriptions with leading spaces, which helps distinguish
    # item names from descriptions.
    price_map = {}  # normalized_item_name → price_cents
    try:
        # Use original raw text (preserves leading spaces on descriptions)
        raw_text = "\n".join(all_pages.values())
        raw_lines = raw_text.split('\n')

        last_item_candidate = None  # The most recent line that looks like an item name

        for i, line in enumerate(raw_lines):
            original_line = line.rstrip('\r')
            stripped = original_line.strip()

            if not stripped:
                continue

            # Check if this line contains a price
            price_match = re.search(r'\$(\d+(?:\.\d{1,2})?)', stripped)
            if price_match:
                price_val = float(price_match.group(1))
                price_cents = int(round(price_val * 100))
                if price_cents > 0 and last_item_candidate:
                    norm = last_item_candidate.upper().strip()
                    # Don't map to navigation/noise items
                    skip_names = {'MORE', 'CHECKOUT', 'CHANGE', 'SIGN IN', 'ORDER NOW',
                                  'HOME', 'MENU', 'ITEMS', 'MOST POPULAR'}
                    if norm not in skip_names and len(norm) > 2:
                        if norm not in price_map:
                            price_map[norm] = price_cents
                # Don't reset candidate — price lines aren't item names
                continue

            # Skip navigation links (markdown format)
            if stripped.startswith('*') or stripped.startswith('[') or stripped.startswith('!'):
                continue
            # Skip category headers (lines followed by --- underlines)
            if i + 1 < len(raw_lines) and set(raw_lines[i + 1].strip()) <= {'-', ' '} and len(raw_lines[i + 1].strip()) > 2:
                last_item_candidate = None  # Reset — this is a category, not an item
                continue
            # Skip horizontal rules
            if set(stripped) <= {'-', '=', '*', ' '} and len(stripped) > 2:
                continue

            # Detect descriptions:
            # 1. Jina Reader: descriptions start with a leading space
            # 2. Playwright: descriptions start with lowercase or ( 
            # 3. Both: descriptions are usually longer sentences
            if original_line.startswith(' ') and not original_line.startswith('  *'):
                continue  # Jina Reader description
            if stripped.startswith('('):
                continue  # Variant description like "(Veg/Chicken)"
            # Skip lines that start with lowercase (descriptions in Playwright format)
            if stripped and stripped[0].islower():
                continue
            # Skip very long uppercase lines (these are descriptions, not item names)
            # e.g. "BRUSSEL SPROUTS AND PARSNIPS MARINATED WITH SPICES AND HERBS..."
            if len(stripped) > 60 and not re.search(r'\$\d', stripped):
                continue

            # skip common noise
            noise_words = {'Pickup from', 'Accepted here', 'Shopping Cart',
                          'Continue Shopping', 'You don', 'Checkout',
                          'Secure checkout', 'Back to Cart', 'Sign Up',
                          'Stay in the Loop', 'This form is', 'Helpful',
                          'Returns Policy', 'ALL SALES', 'Change',
                          'Accepted here', 'Items'}
            if any(stripped.startswith(nw) for nw in noise_words):
                continue

            # This looks like an item name candidate!
            last_item_candidate = stripped

        # Cross-reference: fill $0 items from price map
        if price_map and "categories" in menu_data:
            for cat in menu_data["categories"]:
                for item in cat.get("items", []):
                    current_price = item.get("price_cents", 0) or 0
                    if current_price == 0:
                        item_upper = item.get("name", "").upper().strip()
                        # Exact match first
                        if item_upper in price_map:
                            item["price_cents"] = price_map[item_upper]
                        else:
                            # Fuzzy: check containment both ways
                            best_match = None
                            best_score = 0
                            for map_name, map_price in price_map.items():
                                # Check if either contains the other
                                if item_upper in map_name or map_name in item_upper:
                                    # Score by length of overlap
                                    score = min(len(item_upper), len(map_name))
                                    if score > best_score:
                                        best_score = score
                                        best_match = map_price
                            if best_match:
                                item["price_cents"] = best_match
    except Exception:
        pass  # Price fixing failed, continue with AI prices

    menu_data["pages_scraped"] = pages_scraped

    # Remove empty categories
    if "categories" in menu_data:
        menu_data["categories"] = [c for c in menu_data["categories"] if c.get("items")]

    # Recount
    total_items = sum(len(c.get("items", [])) for c in menu_data.get("categories", []))
    if menu_data.get("error") or total_items == 0:
        # AI returned nothing useful — try regex fallback on raw text and on cleaned content
        raw_text = "\n".join(all_pages.values())
        fallback = _fallback_extract_menu_from_text(raw_text)
        fallback_from_content = _fallback_extract_menu_from_text(content) if content else None
        # Use whichever has more items
        n_raw = sum(len(c.get("items", [])) for c in fallback["categories"]) if fallback and fallback.get("categories") else 0
        n_content = sum(len(c.get("items", [])) for c in fallback_from_content["categories"]) if fallback_from_content and fallback_from_content.get("categories") else 0
        if n_content > n_raw:
            fallback = fallback_from_content
        if fallback and fallback.get("categories"):
            fallback_items = sum(len(c.get("items", [])) for c in fallback["categories"])
            if fallback_items > 0:
                menu_data = fallback
                menu_data["pages_scraped"] = pages_scraped
                print(f"[MenuExtract] AI returned 0 items; used regex fallback: {fallback_items} items")
            else:
                return {"error": f"No menu items found across {pages_scraped} page(s). Try a direct menu page URL or a food delivery page (DoorDash, UberEats, Grubhub)."}
        else:
            return {"error": f"No menu items found across {pages_scraped} page(s). Try a direct menu page URL or a food delivery page (DoorDash, UberEats, Grubhub)."}

    return menu_data


def _norm_import_price_cents(item_data: dict) -> int:
    """Get price_cents from payload; accept price (dollars) or price_cents (cents). Coerce to int. Avoid double conversion."""
    pc = item_data.get("price_cents")
    if pc is not None and pc != "":
        try:
            return int(round(float(pc)))
        except (TypeError, ValueError):
            pass
    price = item_data.get("price")
    if price is not None and price != "":
        try:
            p = float(price)
            # If value looks like cents (whole number >= 1000, e.g. 1299), don't multiply by 100
            if p >= 1000 and p == round(p):
                return int(round(p))
            return int(round(p * 100))
        except (TypeError, ValueError):
            pass
    return 0


@app.post("/owner/restaurants/{restaurant_id}/import-menu")
def save_imported_menu(
    restaurant_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Save AI-extracted menu data into the database."""
    r = db.query(models.Restaurant).filter(
        models.Restaurant.id == restaurant_id,
        models.Restaurant.owner_id == current_user.id,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    categories = payload.get("categories") or []
    if not isinstance(categories, list):
        raise HTTPException(status_code=400, detail="categories must be a list")
    created = {"categories": 0, "items": 0}

    # Trace: log payload shape for debugging
    n_cats = len(categories)
    n_items = sum(len((c.get("items") or [])) for c in categories if isinstance(c, dict))
    print(f"[SaveImportedMenu] restaurant_id={restaurant_id} categories={n_cats} items={n_items}")

    try:
        # Clear existing categories and items for this restaurant to prevent duplicates
        existing_cats = db.query(models.MenuCategory).filter(
            models.MenuCategory.restaurant_id == restaurant_id
        ).all()
        if existing_cats:
            existing_cat_ids = [c.id for c in existing_cats]
            try:
                db.query(models.ChatSession).filter(
                    models.ChatSession.category_id.in_(existing_cat_ids)
                ).update({models.ChatSession.category_id: None}, synchronize_session=False)
            except Exception:
                pass  # column may not exist in older DBs
            # Unlink order_items from menu_items we're about to delete (preserves order history, avoids FK violation)
            menu_ids_to_remove = [r[0] for r in db.query(models.MenuItem.id).filter(
                models.MenuItem.category_id.in_(existing_cat_ids)
            ).all()]
            if menu_ids_to_remove:
                db.query(models.OrderItem).filter(
                    models.OrderItem.menu_item_id.in_(menu_ids_to_remove)
                ).update({models.OrderItem.menu_item_id: None}, synchronize_session=False)
            db.query(models.MenuItem).filter(
                models.MenuItem.category_id.in_(existing_cat_ids)
            ).delete(synchronize_session=False)
            db.query(models.MenuCategory).filter(
                models.MenuCategory.id.in_(existing_cat_ids)
            ).delete(synchronize_session=False)
            db.flush()

        for i, cat_data in enumerate(categories):
            if not isinstance(cat_data, dict):
                continue
            cat_name = str(cat_data.get("name") or f"Category {i+1}")[:120].strip() or f"Category {i+1}"
            cat = models.MenuCategory(
                restaurant_id=restaurant_id,
                name=cat_name,
                sort_order=i + 1,
            )
            db.add(cat)
            db.flush()
            created["categories"] += 1

            for item_data in (cat_data.get("items") or []):
                if not isinstance(item_data, dict):
                    continue
                raw_name = item_data.get("name")
                name = (str(raw_name) if raw_name is not None else "Unknown").strip()[:160] or "Unknown"
                raw_desc = item_data.get("description")
                desc = None
                if raw_desc is not None and str(raw_desc).strip():
                    desc = str(raw_desc)[:2000].strip() or None
                price_cents = max(0, int(_norm_import_price_cents(item_data)))
                item = models.MenuItem(
                    category_id=cat.id,
                    name=name,
                    description=desc,
                    price_cents=price_cents,
                    is_available=True,
                )
                db.add(item)
                created["items"] += 1

        db.commit()
        return {"ok": True, "created": created}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        print(f"[SaveImportedMenu] Error: {e}")
        err_msg = str(e)
        raise HTTPException(status_code=500, detail=f"Failed to save menu: {err_msg}")
