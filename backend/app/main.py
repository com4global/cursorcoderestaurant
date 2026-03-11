from __future__ import annotations

import json as _json
import os
import urllib.request
import urllib.error
import urllib.parse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import chat, crud, models, payments, schemas
from .auth import create_access_token, get_current_user, verify_password
from .config import settings
from .db import get_db, engine
from .voice import router as voice_router

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="RestarentAI")
app.include_router(voice_router)

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


# --- Multi-restaurant cart helper ---
def _build_cart_summary(db: Session, user_id: int) -> dict:
    """Build grouped cart data across all pending orders for a user."""
    pending_orders = crud.get_user_pending_orders(db, user_id)
    groups = []
    grand_total = 0
    for order in pending_orders:
        restaurant = db.query(models.Restaurant).filter(models.Restaurant.id == order.restaurant_id).first()
        items = []
        for oi in order.items:
            mi = db.query(models.MenuItem).filter(models.MenuItem.id == oi.menu_item_id).first()
            line_total = oi.price_cents * oi.quantity
            items.append({
                "name": mi.name if mi else f"Item #{oi.menu_item_id}",
                "quantity": oi.quantity,
                "price_cents": oi.price_cents,
                "line_total_cents": line_total,
            })
        if items:
            groups.append({
                "restaurant_id": order.restaurant_id,
                "restaurant_name": restaurant.name if restaurant else "Unknown",
                "order_id": order.id,
                "items": items,
                "subtotal_cents": order.total_cents,
            })
            grand_total += order.total_cents
    return {"restaurants": groups, "grand_total_cents": grand_total}


@app.get("/cart")
def get_cart(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get all pending orders grouped by restaurant for the current user."""
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
    all_restaurants = crud.list_restaurants(db, query)

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

    return all_restaurants


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
        session = (
            db.query(models.ChatSession)
            .filter(models.ChatSession.id == payload.session_id)
            .first()
        )
        if not session or session.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    crud.add_chat_message(db, session.id, "user", payload.text)
    result = chat.process_message(db, session, payload.text)
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
    item = models.MenuItem(category_id=category_id, name=payload.name, description=payload.description, price_cents=payload.price_cents, is_available=payload.is_available)
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
    order.status = new_status
    db.commit()
    return {"ok": True, "order_id": order_id, "status": new_status}


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


# --- Stripe Webhook ---
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    return payments.handle_stripe_webhook(payload, sig_header, db)



# --- Customer: My Orders (track status) ---
@app.get("/my-orders")
def my_orders(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Get all non-pending orders for the current customer, newest first."""
    orders = db.query(models.Order).filter(
        models.Order.user_id == current_user.id,
        models.Order.status != "pending"
    ).order_by(models.Order.created_at.desc()).limit(20).all()
    results = []
    for o in orders:
        rest = db.query(models.Restaurant).get(o.restaurant_id)
        items = []
        for oi in o.items:
            mi = db.query(models.MenuItem).get(oi.menu_item_id)
            items.append({"name": mi.name if mi else "?", "quantity": oi.quantity, "price_cents": oi.price_cents})
        results.append({
            "id": o.id,
            "status": o.status,
            "total_cents": o.total_cents,
            "created_at": o.created_at.isoformat(),
            "restaurant_name": rest.name if rest else "?",
            "restaurant_id": o.restaurant_id,
            "items": items,
        })
    return results


# --- /me endpoint ---
@app.get("/auth/me", response_model=schemas.UserOut)
def get_me(current_user=Depends(get_current_user)):
    return current_user


# =============================================================
# AI Menu Extraction (Phase 3 integrated into Phase 2)
# =============================================================

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

    from urllib.parse import urljoin, urlparse
    import re

    def _fetch_rendered(target_url: str) -> str:
        """Fetch a URL with full JS rendering + scrolling + category clicking."""
        # --- Try Playwright first (clicks categories + scrolls for lazy content) ---
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(target_url, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(8000)  # Extra wait for SPA frameworks to fetch API data and render

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

                    # Click each category element to force-load its items
                    clicked = set()
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
                            page.wait_for_timeout(2000)  # Wait for SPA to fetch + render
                            # Scroll content area to trigger lazy rendering within category
                            page.evaluate("window.scrollBy(0, 400)")
                            page.wait_for_timeout(500)
                        except Exception:
                            continue

                except Exception:
                    pass

                # Step 3: Final full scroll to capture everything
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
                for _ in range(50):
                    page.evaluate("window.scrollBy(0, 600)")
                    page.wait_for_timeout(300)
                    curr = page.evaluate("document.body.scrollHeight")
                    scroll_pos = page.evaluate("window.scrollY + window.innerHeight")
                    if scroll_pos >= curr:
                        break

                # Extract text — try structured extraction first, then fall back to innerText
                text = page.evaluate("""() => {
                    // Remove non-content elements
                    document.querySelectorAll('script, style, noscript, svg, nav, footer, header').forEach(el => el.remove());
                    
                    // Try to find menu item cards/containers for structured extraction
                    const items = [];
                    const cardSelectors = [
                        '[class*="menu-item"]', '[class*="menuItem"]', '[class*="item-card"]',
                        '[class*="product-card"]', '[class*="food-item"]', '[class*="dish"]',
                        '[data-testid*="item"]', '[data-testid*="product"]',
                        '.item', '.product', '.menu-card'
                    ];
                    
                    for (const sel of cardSelectors) {
                        const cards = document.querySelectorAll(sel);
                        if (cards.length > 3) {
                            cards.forEach(card => {
                                const t = card.innerText.trim();
                                if (t && t.length > 5) items.push(t);
                            });
                            break;
                        }
                    }
                    
                    if (items.length > 5) {
                        return items.join('\n---\n');
                    }
                    
                    // Fallback: plain innerText
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
        # Keep up to 15000 chars per page
        clean = clean[:15000]
        if len(clean) > 100:
            label = page_url.split("//", 1)[-1]
            combined_parts.append(f"=== PAGE: {label} ===\n{clean}")

    content = "\n\n".join(combined_parts)
    pages_scraped = len(all_pages)

    if len(content) < 100:
        return {"error": "Could not extract content from this website. Try a direct menu page URL or a food delivery page (DoorDash, UberEats, Grubhub)."}

    # Limit total content for the LLM
    content = content[:40000]

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
            menu_data = _json.loads(response_text)
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

        # --- 6B: Gemini text fallback (if still low items) ---
        if total_items < 10:
            try:
                text_prompt = f"""{gemini_extraction_prompt}

Website text content:
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

                text_items = sum(len(c.get("items", [])) for c in text_menu.get("categories", []))
                if text_items > total_items:
                    menu_data = text_menu
                    total_items = text_items
            except Exception as e:
                print(f"[AI] Gemini text error: {e}")

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
        return {"error": f"No menu items found across {pages_scraped} page(s). Try a direct menu page URL or a food delivery page (DoorDash, UberEats, Grubhub)."}

    return menu_data


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

    categories = payload.get("categories", [])
    created = {"categories": 0, "items": 0}

    for i, cat_data in enumerate(categories):
        cat = models.MenuCategory(
            restaurant_id=restaurant_id,
            name=cat_data.get("name", f"Category {i+1}"),
            sort_order=i + 1,
        )
        db.add(cat)
        db.flush()
        created["categories"] += 1

        for item_data in cat_data.get("items", []):
            item = models.MenuItem(
                category_id=cat.id,
                name=item_data.get("name", "Unknown"),
                description=item_data.get("description", ""),
                price_cents=item_data.get("price_cents", 0),
                is_available=True,
            )
            db.add(item)
            created["items"] += 1

    db.commit()
    return {"ok": True, "created": created}
