
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import chat, crud, models, schemas
from .auth import create_access_token, get_current_user, verify_password
from .config import settings
from .db import get_db, engine

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="RestarentAI")

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


@app.post("/auth/register", response_model=schemas.Token)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if crud.get_user_by_email(db, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = crud.create_user(db, payload.email, payload.password)
    token = create_access_token(user.email)
    return {"access_token": token}


@app.post("/auth/login", response_model=schemas.Token)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.email)
    return {"access_token": token}


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
            if r.latitude is not None and r.longitude is not None:
                dist = _haversine(lat, lng, r.latitude, r.longitude)
                if dist <= radius_miles:
                    out = schemas.RestaurantOut.model_validate(r)
                    out.distance_miles = round(dist, 1)
                    results.append(out)
            else:
                # Restaurants without coords always show (for now)
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
    """Register as a restaurant owner."""
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    from passlib.hash import bcrypt
    user = models.User(
        email=payload.email,
        password_hash=bcrypt.hash(payload.password),
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.email)
    return {"access_token": token}


# --- My restaurants ---
@app.get("/owner/restaurants", response_model=list[schemas.RestaurantOut])
def owner_restaurants(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")
    return db.query(models.Restaurant).filter(models.Restaurant.owner_id == current_user.id).all()


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
    r = models.Restaurant(
        owner_id=current_user.id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        city=payload.city,
        address=payload.address,
        zipcode=payload.zipcode,
        latitude=payload.latitude,
        longitude=payload.longitude,
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
def owner_orders(restaurant_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    r = db.query(models.Restaurant).filter(models.Restaurant.id == restaurant_id, models.Restaurant.owner_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    orders = db.query(models.Order).filter(models.Order.restaurant_id == restaurant_id).order_by(models.Order.created_at.desc()).limit(50).all()
    results = []
    for o in orders:
        items = []
        for oi in o.items:
            mi = db.query(models.MenuItem).get(oi.menu_item_id)
            items.append({"name": mi.name if mi else "?", "qty": oi.quantity, "price_cents": oi.price_cents})
        results.append({
            "id": o.id,
            "status": o.status,
            "total_cents": o.total_cents,
            "created_at": o.created_at.isoformat(),
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

from bs4 import BeautifulSoup
import os

@app.post("/owner/import-menu")
def import_menu_from_url(
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Scrape a restaurant website and extract menu using Gemini AI."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not a restaurant owner")

    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # 1. Scrape the website
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        response = urllib.request.urlopen(req, timeout=15)
        html = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {str(e)}")

    # 2. Extract clean text using BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    # Remove scripts, styles, nav, footer
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Limit to 8000 chars for the LLM
    text = text[:8000]

    # 3. Send to OpenAI for extraction
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    try:
        prompt = f"""Extract the restaurant menu from this website text.

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
- Group items into logical categories (Appetizers, Mains, Drinks, Desserts, etc.)
- Keep descriptions short (under 50 chars)
- If you can't find a menu, return {{"error": "No menu found"}}

Website text:
{text}"""

        # OpenAI REST API with json_mode
        oai_url = "https://api.openai.com/v1/chat/completions"
        oai_body = _json.dumps({
            "model": "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You extract restaurant menus from website text and return structured JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }).encode()

        oai_req = urllib.request.Request(oai_url, oai_body, {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        oai_res = urllib.request.urlopen(oai_req, timeout=60)
        oai_data = _json.loads(oai_res.read())
        response_text = oai_data["choices"][0]["message"]["content"].strip()

        menu_data = _json.loads(response_text)
        return menu_data

    except urllib.error.HTTPError as http_err:
        err_body = http_err.read().decode()[:300]
        raise HTTPException(status_code=503, detail=f"OpenAI API error ({http_err.code}): {err_body}")
    except _json.JSONDecodeError:
        return {"error": "AI could not parse menu properly", "raw": response_text[:500] if response_text else ""}
    except HTTPException:
        raise


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
