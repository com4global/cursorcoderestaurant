"""
Chat engine with natural-language ordering and structured responses.

Returns dicts with:
  - reply: text message
  - restaurant_id, category_id, order_id: session state
  - categories: list of category dicts (for interactive chips)
  - items: list of item dicts (for interactive cards)
"""

import re
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from . import crud
from .models import ChatSession, MenuItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(reply, restaurant_id=None, category_id=None, order_id=None,
            categories=None, items=None):
    return {
        "reply": reply,
        "restaurant_id": restaurant_id,
        "category_id": category_id,
        "order_id": order_id,
        "categories": categories,
        "items": items,
    }


def _set_session_state(db: Session, session: ChatSession, **updates) -> None:
    for key, value in updates.items():
        setattr(session, key, value)
    session.updated_at = datetime.utcnow()
    db.commit()


def _categories_data(db, restaurant_id):
    """Return categories as structured dicts with item counts."""
    categories = crud.list_categories(db, restaurant_id)
    result = []
    for cat in categories:
        items = crud.list_items(db, cat.id)
        result.append({
            "id": cat.id,
            "name": cat.name,
            "item_count": len(items),
        })
    return result


def _items_data(db, category_id):
    """Return items in a category as structured dicts."""
    items = crud.list_items(db, category_id)
    return [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description or "",
            "price_cents": item.price_cents,
        }
        for item in items
    ]


# ---------------------------------------------------------------------------
# Fuzzy item matching
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_best_item(query: str, all_items: list[MenuItem]) -> MenuItem | None:
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    for item in all_items:
        if item.name.lower() == query_lower:
            return item

    for item in all_items:
        if query_lower in item.name.lower() or item.name.lower() in query_lower:
            return item

    best_item, best_score = None, 0.0
    for item in all_items:
        score = _similarity(query_lower, item.name.lower())
        for word in item.name.lower().split():
            score = max(score, _similarity(query_lower, word))
        if score > best_score:
            best_score = score
            best_item = item
    return best_item if best_score >= 0.55 else None


def _find_matching_items(query: str, all_items: list[MenuItem], limit=5) -> list[MenuItem]:
    """Find multiple matching items for a search query."""
    query_lower = query.lower().strip()
    scored = []
    for item in all_items:
        score = _similarity(query_lower, item.name.lower())
        if query_lower in item.name.lower():
            score = max(score, 0.8)
        for word in item.name.lower().split():
            score = max(score, _similarity(query_lower, word))
        if score >= 0.4:
            scored.append((item, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [item for item, _ in scored[:limit]]


def _parse_order_items(text: str, all_items: list[MenuItem]) -> list[tuple[MenuItem, int]]:
    word_to_num = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }

    cleaned = text.lower().strip()
    for filler in ["i want", "i'd like", "i would like", "give me", "get me",
                   "can i have", "can i get", "please", "order", "add"]:
        cleaned = cleaned.replace(filler, "")
    cleaned = cleaned.strip().strip(",").strip()

    if not cleaned:
        return []

    parts = re.split(r'\s*(?:,\s*and|\band\b|,|&|\+)\s*', cleaned)

    results = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        quantity = 1
        num_match = re.match(r'^(\d+)\s+(.+)', part)
        if num_match:
            quantity = int(num_match.group(1))
            part = num_match.group(2).strip()
        else:
            words = part.split()
            if words and words[0] in word_to_num:
                quantity = word_to_num[words[0]]
                part = " ".join(words[1:]).strip()

        trailing = re.match(r'(.+?)\s*x\s*(\d+)$', part)
        if trailing:
            part = trailing.group(1).strip()
            quantity = int(trailing.group(2))

        item = _find_best_item(part, all_items)
        if item:
            results.append((item, quantity))

    return results


def _get_all_restaurant_items(db: Session, restaurant_id: int) -> list[MenuItem]:
    categories = crud.list_categories(db, restaurant_id)
    all_items = []
    for cat in categories:
        all_items.extend(crud.list_items(db, cat.id))
    return all_items


# ---------------------------------------------------------------------------
# Main message processor
# ---------------------------------------------------------------------------

def process_message(db: Session, session: ChatSession, text: str) -> dict:
    cleaned = text.strip()
    lower = cleaned.lower()

    # --- Reset / Exit ---
    if lower in ("#reset", "#exit", "reset", "exit", "start over"):
        _set_session_state(db, session, restaurant_id=None, category_id=None, order_id=None)
        return _result("Session reset. Type # to pick a restaurant!")

    # --- Restaurant selection via #slug ---
    if cleaned.startswith("#"):
        slug = cleaned.lstrip("#").strip().lower()
        if not slug:
            return _result("Type # followed by a restaurant name to get started.")

        restaurant = crud.get_restaurant_by_slug_or_id(db, slug)
        if not restaurant:
            restaurants = crud.list_restaurants(db)
            for r in restaurants:
                if _similarity(slug, r.slug) >= 0.6 or _similarity(slug, r.name.lower()) >= 0.6:
                    restaurant = r
                    break

        if not restaurant:
            return _result("Restaurant not found. Type # to see suggestions.")

        _set_session_state(db, session, restaurant_id=restaurant.id, category_id=None, order_id=None)
        cats = _categories_data(db, restaurant.id)

        reply = f"Welcome to {restaurant.name}! Pick a category or just tell me what you want."
        return _result(reply, restaurant_id=restaurant.id, categories=cats)

    # --- If no restaurant selected yet ---
    if session.restaurant_id is None:
        return _result("Type # to pick a restaurant and start ordering!")

    # --- Browse category by name or id ---
    if lower.startswith("category:") or lower.startswith("browse:"):
        cat_query = cleaned.split(":", 1)[1].strip()
        categories = crud.list_categories(db, session.restaurant_id)
        match = None
        for cat in categories:
            if str(cat.id) == cat_query or cat.name.lower() == cat_query.lower():
                match = cat
                break
        if match:
            items = _items_data(db, match.id)
            return _result(
                f"{match.name} — {len(items)} items. Tap to add or type what you want!",
                restaurant_id=session.restaurant_id,
                category_id=match.id,
                order_id=session.order_id,
                items=items,
            )

    # Also match if user just types a category name
    categories = crud.list_categories(db, session.restaurant_id)
    cat_match = None
    for cat in categories:
        if cat.name.lower() == lower or str(cat.id) == lower:
            cat_match = cat
            break
    if not cat_match:
        for cat in categories:
            if _similarity(lower, cat.name.lower()) >= 0.7:
                cat_match = cat
                break

    if cat_match:
        items = _items_data(db, cat_match.id)
        return _result(
            f"{cat_match.name} — {len(items)} items. Tap + to add or just tell me what you want!",
            restaurant_id=session.restaurant_id,
            category_id=cat_match.id,
            order_id=session.order_id,
            items=items,
        )

    # --- Show menu / categories ---
    if lower in ("menu", "show menu", "categories", "show categories", "what do you have"):
        cats = _categories_data(db, session.restaurant_id)
        return _result(
            "Here are the categories. Tap one to browse!",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
        )

    # --- Submit order ---
    if lower in ("#order", "submit", "submit order", "place order", "done",
                 "checkout", "check out", "that's all", "thats all", "confirm",
                 "place my order", "send order"):
        if session.order_id is None:
            return _result(
                "Your cart is empty! Pick a category or tell me what you want.",
                restaurant_id=session.restaurant_id,
            )
        order = crud.get_order(db, session.order_id)
        if not order:
            _set_session_state(db, session, order_id=None)
            return _result("Cart not found. Tell me what you want to order!",
                          restaurant_id=session.restaurant_id)
        order.status = "submitted"
        db.commit()
        total = f"${order.total_cents / 100:.2f}"
        return _result(
            f"Order #{order.id} submitted! Total: {total}. Your order has been sent to the restaurant!",
            restaurant_id=session.restaurant_id,
            order_id=order.id,
        )

    # --- View cart ---
    if lower in ("cart", "my cart", "show cart", "view cart", "what's in my cart"):
        if session.order_id is None:
            return _result("Your cart is empty! Just tell me what you want.",
                          restaurant_id=session.restaurant_id)
        order = crud.get_order(db, session.order_id)
        if not order or not order.items:
            return _result("Your cart is empty!",
                          restaurant_id=session.restaurant_id)
        lines = ["Your Cart:\n"]
        for oi in order.items:
            mi = db.query(MenuItem).filter(MenuItem.id == oi.menu_item_id).first()
            name = mi.name if mi else f"Item #{oi.menu_item_id}"
            lines.append(f"  {oi.quantity}x {name} - ${oi.price_cents * oi.quantity / 100:.2f}")
        lines.append(f"\nTotal: ${order.total_cents / 100:.2f}")
        lines.append('\nSay "submit" to place your order!')
        return _result("\n".join(lines),
                      restaurant_id=session.restaurant_id,
                      order_id=order.id)

    # --- Quick add by item ID (from tapping + button) ---
    quick_add = re.match(r'^add:(\d+)(?::(\d+))?$', lower)
    if quick_add:
        item_id = int(quick_add.group(1))
        quantity = int(quick_add.group(2) or 1)
        all_items = _get_all_restaurant_items(db, session.restaurant_id)
        menu_item = next((i for i in all_items if i.id == item_id), None)
        if menu_item:
            if session.order_id is None:
                order = crud.create_order(db, session.user_id, session.restaurant_id)
                crud.attach_order_to_session(db, session, order)
            else:
                order = crud.get_order(db, session.order_id)
                if not order:
                    order = crud.create_order(db, session.user_id, session.restaurant_id)
                    crud.attach_order_to_session(db, session, order)

            crud.add_order_item(db, order, menu_item, quantity)
            crud.recompute_order_total(db, order)
            total = f"${order.total_cents / 100:.2f}"
            return _result(
                f"Added {quantity}x {menu_item.name}! Cart total: {total}",
                restaurant_id=session.restaurant_id,
                order_id=order.id,
            )
        return _result("Item not found.", restaurant_id=session.restaurant_id)

    # --- Natural language ordering ---
    all_items = _get_all_restaurant_items(db, session.restaurant_id)
    parsed = _parse_order_items(cleaned, all_items)

    if not parsed:
        single_match = _find_best_item(cleaned, all_items)
        if single_match:
            parsed = [(single_match, 1)]

    if not parsed:
        # Try search and show matching items
        matches = _find_matching_items(cleaned, all_items)
        if matches:
            items_data = [
                {
                    "id": m.id,
                    "name": m.name,
                    "description": m.description or "",
                    "price_cents": m.price_cents,
                }
                for m in matches
            ]
            return _result(
                f'Found {len(matches)} items matching "{cleaned}". Tap + to add!',
                restaurant_id=session.restaurant_id,
                order_id=session.order_id,
                items=items_data,
            )

        # Show categories as fallback
        cats = _categories_data(db, session.restaurant_id)
        return _result(
            "I didn't catch that. Pick a category or type what you want!",
            restaurant_id=session.restaurant_id,
            order_id=session.order_id,
            categories=cats,
        )

    # Create or get order
    if session.order_id is None:
        order = crud.create_order(db, session.user_id, session.restaurant_id)
        crud.attach_order_to_session(db, session, order)
    else:
        order = crud.get_order(db, session.order_id)
        if not order:
            order = crud.create_order(db, session.user_id, session.restaurant_id)
            crud.attach_order_to_session(db, session, order)

    added_lines = []
    for menu_item, qty in parsed:
        crud.add_order_item(db, order, menu_item, qty)
        price = f"${menu_item.price_cents * qty / 100:.2f}"
        added_lines.append(f"  {qty}x {menu_item.name} - {price}")

    crud.recompute_order_total(db, order)
    total = f"${order.total_cents / 100:.2f}"
    reply = "Added to your order:\n" + "\n".join(added_lines)
    reply += f"\n\nCart total: {total}"

    return _result(reply,
                  restaurant_id=session.restaurant_id,
                  order_id=order.id)
