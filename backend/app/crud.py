from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import (
    ChatMessage,
    ChatSession,
    MenuCategory,
    MenuItem,
    Order,
    OrderItem,
    OrderFeedback,
    Payment,
    Restaurant,
    TasteProfile,
    User,
)
from collections import Counter


def create_user(db: Session, email: str, password: str) -> User:
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def list_restaurants(db: Session, query: str | None = None) -> list[Restaurant]:
    stmt = db.query(Restaurant).filter(Restaurant.is_active.is_(True))
    if query:
        like = f"%{query.lower()}%"
        stmt = stmt.filter(func.lower(Restaurant.name).like(like))
    return stmt.order_by(Restaurant.name.asc()).all()


def get_restaurant_by_slug_or_id(db: Session, slug_or_id: str) -> Restaurant | None:
    if slug_or_id.isdigit():
        return db.query(Restaurant).filter(Restaurant.id == int(slug_or_id)).first()
    return db.query(Restaurant).filter(Restaurant.slug == slug_or_id).first()


def list_categories(db: Session, restaurant_id: int) -> list[MenuCategory]:
    return (
        db.query(MenuCategory)
        .filter(MenuCategory.restaurant_id == restaurant_id)
        .order_by(MenuCategory.sort_order.asc())
        .all()
    )


def list_items(db: Session, category_id: int) -> list[MenuItem]:
    return (
        db.query(MenuItem)
        .filter(MenuItem.category_id == category_id)
        .filter(MenuItem.is_available.is_(True))
        .order_by(MenuItem.name.asc())
        .all()
    )


def create_chat_session(db: Session, user_id: int) -> ChatSession:
    session = ChatSession(user_id=user_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def add_chat_message(db: Session, session_id: int, role: str, content: str) -> ChatMessage:
    message = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(message)
    db.commit()
    return message


def create_order(db: Session, user_id: int, restaurant_id: int) -> Order:
    order = Order(user_id=user_id, restaurant_id=restaurant_id, status="pending")
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: int) -> Order | None:
    return db.query(Order).filter(Order.id == order_id).first()


def attach_order_to_session(db: Session, session: ChatSession, order: Order) -> None:
    session.order_id = order.id
    db.commit()
    db.refresh(session)


def add_order_item(
    db: Session, order: Order, menu_item: MenuItem, quantity: int
) -> OrderItem:
    # Check if this item already exists in the order — if so, increment quantity
    existing = (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order.id, OrderItem.menu_item_id == menu_item.id)
        .first()
    )
    if existing:
        existing.quantity += quantity
        db.commit()
        db.refresh(existing)
        return existing

    item = OrderItem(
        order_id=order.id,
        menu_item_id=menu_item.id,
        quantity=quantity,
        price_cents=menu_item.price_cents,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def recompute_order_total(db: Session, order: Order) -> None:
    total = (
        db.query(func.coalesce(func.sum(OrderItem.price_cents * OrderItem.quantity), 0))
        .filter(OrderItem.order_id == order.id)
        .scalar()
    )
    order.total_cents = int(total or 0)
    db.commit()


def get_user_pending_orders(db: Session, user_id: int) -> list[Order]:
    """Return all pending orders for a user (across all restaurants)."""
    return (
        db.query(Order)
        .filter(Order.user_id == user_id, Order.status == "pending")
        .all()
    )


def get_user_order_for_restaurant(db: Session, user_id: int, restaurant_id: int) -> Order | None:
    """Find existing pending order for a specific restaurant."""
    return (
        db.query(Order)
        .filter(
            Order.user_id == user_id,
            Order.restaurant_id == restaurant_id,
            Order.status == "pending",
        )
        .first()
    )


def clear_user_pending_orders(db: Session, user_id: int) -> None:
    """Clear all pending orders for a user (cart clear). Detach chat sessions and payments first."""
    pending = get_user_pending_orders(db, user_id)
    for order in pending:
        for oi in order.items:
            db.delete(oi)
        db.query(ChatSession).filter(ChatSession.order_id == order.id).update({"order_id": None})
        db.query(Payment).filter(Payment.order_id == order.id).update({"order_id": None})
        db.delete(order)
    db.commit()


# --- Taste Profile ---

def get_taste_profile(db: Session, user_id: int) -> TasteProfile | None:
    return db.query(TasteProfile).filter(TasteProfile.user_id == user_id).first()


def upsert_taste_profile(
    db: Session,
    user_id: int,
    *,
    spice_level: str | None = None,
    diet: str | None = None,
    liked_cuisines: list[str] | None = None,
    disliked_tags: str | None = None,
) -> TasteProfile:
    import json
    profile = get_taste_profile(db, user_id)
    if not profile:
        profile = TasteProfile(
            user_id=user_id,
            spice_level=spice_level or "medium",
            diet=diet,
            liked_cuisines=json.dumps(liked_cuisines or []) if liked_cuisines is not None else "[]",
            disliked_tags=disliked_tags,
        )
        db.add(profile)
    else:
        if spice_level is not None:
            profile.spice_level = spice_level
        if diet is not None:
            profile.diet = diet
        if liked_cuisines is not None:
            profile.liked_cuisines = json.dumps(liked_cuisines)
        if disliked_tags is not None:
            profile.disliked_tags = disliked_tags or None
    db.commit()
    db.refresh(profile)
    return profile


def get_order_history_taste_summary(db: Session, user_id: int, limit_orders: int = 50) -> dict:
    """Build taste vector from completed orders: item ids, cuisine/protein counts, item names."""
    orders = (
        db.query(Order)
        .filter(Order.user_id == user_id, Order.status == "completed")
        .order_by(Order.created_at.desc())
        .limit(limit_orders)
        .all()
    )
    ordered_item_ids = []
    cuisine_counts = Counter()
    protein_counts = Counter()
    item_names = []
    seen_names = set()
    for order in orders:
        for oi in order.items:
            mi = db.query(MenuItem).filter(MenuItem.id == oi.menu_item_id).first()
            if not mi:
                continue
            for _ in range(oi.quantity):
                ordered_item_ids.append(mi.id)
            if mi.cuisine:
                cuisine_counts[mi.cuisine.strip()] += oi.quantity
            if mi.protein_type:
                protein_counts[mi.protein_type.strip().lower()] += oi.quantity
            if mi.name and mi.name.strip() not in seen_names:
                seen_names.add(mi.name.strip())
                item_names.append(mi.name.strip())
    return {
        "ordered_item_ids": ordered_item_ids,
        "cuisine_counts": dict(cuisine_counts),
        "protein_counts": dict(protein_counts),
        "item_names": item_names[:30],
        "total_orders": len(orders),
    }


def get_taste_recommendations(
    db: Session, user_id: int, limit: int = 10
) -> list[dict]:
    """Personalized item recommendations from profile + order history + item tags."""
    import json
    from .taste_tags import derive_item_tags

    profile = get_taste_profile(db, user_id)
    history = get_order_history_taste_summary(db, user_id)
    ordered_ids = set(history["ordered_item_ids"])
    liked_cuisines = set()
    diet_tag = None
    disliked_set = set()
    if profile:
        try:
            raw = json.loads(profile.liked_cuisines) if profile.liked_cuisines else []
            liked_cuisines = { str(c).strip().lower().replace(" ", "-") for c in raw }
        except (TypeError, json.JSONDecodeError):
            pass
        if profile.diet:
            diet_tag = profile.diet.strip().lower().replace(" ", "-")
        if profile.disliked_tags:
            disliked_set = { t.strip().lower() for t in profile.disliked_tags.split(",") if t.strip() }

    restaurant_ids = set()
    if history["total_orders"] > 0:
        orders = (
            db.query(Order)
            .filter(Order.user_id == user_id, Order.status == "completed")
            .limit(20)
            .all()
        )
        restaurant_ids = { o.restaurant_id for o in orders }
    if not restaurant_ids:
        restaurant_ids = { r.id for r in db.query(Restaurant).filter(Restaurant.is_active.is_(True)).limit(10).all() }

    candidates = []
    for rid in restaurant_ids:
        cats = list_categories(db, rid)
        for c in cats:
            for item in list_items(db, c.id):
                if item.id in ordered_ids:
                    continue
                raw_tags = item.tags
                try:
                    tags = set(json.loads(raw_tags)) if raw_tags else set()
                except (TypeError, json.JSONDecodeError):
                    tags = set(derive_item_tags(item.name, item.cuisine, item.protein_type))
                if not tags:
                    tags = set(derive_item_tags(item.name, item.cuisine, item.protein_type))
                score = 0
                reason_parts = []
                for t in tags:
                    if t in disliked_set:
                        score -= 10
                        break
                if score < 0:
                    continue
                for t in tags:
                    if t in liked_cuisines:
                        score += 3
                        reason_parts.append(f"you like {t}")
                if diet_tag and diet_tag in tags:
                    score += 5
                    reason_parts.append(f"matches your {profile.diet} preference")
                for name in history["item_names"][:10]:
                    if name and name.lower() in (item.name or "").lower():
                        score += 2
                    if item.cuisine and item.cuisine.lower() in (history.get("cuisine_counts") or {}):
                        score += 2
                if history["item_names"] and not reason_parts:
                    reason_parts.append(f"Based on your order history")
                if not reason_parts:
                    reason_parts.append("Try something new")
                rest = db.query(Restaurant).filter(Restaurant.id == rid).first()
                candidates.append({
                    "score": score,
                    "menu_item_id": item.id,
                    "name": item.name,
                    "restaurant_id": rid,
                    "restaurant_name": rest.name if rest else "?",
                    "price_cents": item.price_cents,
                    "reason": " — ".join(reason_parts[:2]) if reason_parts else "Recommended for you",
                })
    candidates.sort(key=lambda x: -x["score"])
    return [{"menu_item_id": c["menu_item_id"], "name": c["name"], "restaurant_id": c["restaurant_id"], "restaurant_name": c["restaurant_name"], "price_cents": c["price_cents"], "reason": c["reason"]} for c in candidates[:limit]]


# --- Order Feedback ---

def get_feedback_by_order(db: Session, order_id: int) -> OrderFeedback | None:
    return db.query(OrderFeedback).filter(OrderFeedback.order_id == order_id).first()


def create_feedback(
    db: Session,
    user_id: int,
    order_id: int,
    rating: int,
    *,
    issues: list[str] | None = None,
    comment: str | None = None,
    photo_url: str | None = None,
) -> OrderFeedback:
    import json
    fb = OrderFeedback(
        user_id=user_id,
        order_id=order_id,
        rating=rating,
        issues=json.dumps(issues or []) if issues else None,
        comment=comment,
        photo_url=photo_url,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb


def list_complaints_for_restaurant(db: Session, restaurant_id: int, limit: int = 50) -> list[dict]:
    """List escalated feedback (rating <= 2) for restaurant dashboard."""
    import json
    feedbacks = (
        db.query(OrderFeedback)
        .join(Order)
        .filter(Order.restaurant_id == restaurant_id, OrderFeedback.rating <= 2)
        .order_by(OrderFeedback.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for fb in feedbacks:
        order = db.query(Order).filter(Order.id == fb.order_id).first()
        rest = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
        items = []
        for oi in order.items:
            mi = db.query(MenuItem).filter(MenuItem.id == oi.menu_item_id).first()
            items.append(f"{oi.quantity}x {mi.name}" if mi else "?")
        out.append({
            "id": fb.id,
            "order_id": fb.order_id,
            "user_id": fb.user_id,
            "rating": fb.rating,
            "issues": json.loads(fb.issues) if fb.issues else [],
            "comment": fb.comment,
            "photo_url": fb.photo_url,
            "created_at": fb.created_at.isoformat(),
            "restaurant_id": restaurant_id,
            "restaurant_name": rest.name if rest else "?",
            "order_items_summary": ", ".join(items),
        })
    return out
